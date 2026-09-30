"""Why does the pipeline underperform the offline test? Compare, frame by frame on the demo video:

  A. classifier on the ground-truth box crop (what it was trained/tested on)
  B. classifier on the pipeline-style crop (YOLO motorcycle box ∪ overlapping person boxes)
  C. detection recall: does YOLO find a motorcycle for each labelled motorcycle?

Also saves side-by-side examples of A vs B crops.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from roadguard.pipeline.helmet import letterbox_square  # noqa: E402

ANN = BACKEND / "data" / "datasets" / "helmet_osf"


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def overlap(inner, outer):
    x1, y1, x2, y2 = max(inner[0], outer[0]), max(inner[1], outer[1]), min(inner[2], outer[2]), min(inner[3], outer[3])
    return max(0, x2 - x1) * max(0, y2 - y1) / max(1e-6, (inner[2] - inner[0]) * (inner[3] - inner[1]))


def pad_crop(img, box, pad=0.08):
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    return img[int(max(0, y1 - 1.5 * py)):int(min(H, y2 + py)), int(max(0, x1 - px)):int(min(W, x2 + px))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(BACKEND / "data/samples/helmet_demo_mandalay.mp4"))
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--rider-overlap", type=float, default=0.3)
    ap.add_argument("--out", default=str(BACKEND / "runs" / "helmet_diag"))
    a = ap.parse_args()

    from ultralytics import YOLO

    det = YOLO(str(BACKEND / "yolov8n.pt"))
    cls = YOLO(str(BACKEND / "models" / "helmet_cls.pt"))
    no_id = next(k for k, v in cls.names.items() if v == "no_helmet")

    gt = defaultdict(list)
    for ci, clip in enumerate(a.clips):
        for r in csv.DictReader(open(next(ANN.rglob(f"annotation/**/{clip}.csv")))):
            x, y, w, h = (float(r[k]) for k in "xywh")
            if h >= 80:
                gt[ci * 100 + int(r["frame_id"]) - 1].append(((x, y, x + w, y + h), "NoHelmet" in r["label"]))

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res = {"A": [], "B": []}
    found, total, saved = 0, 0, 0
    cap = cv2.VideoCapture(a.video)
    fi = -1
    while True:
        ok, img = cap.read()
        fi += 1
        if not ok:
            break
        if fi % a.every or fi not in gt:
            continue
        r = det.predict(img, classes=[0, 3], conf=0.3, imgsz=640, verbose=False)[0]
        motos = [b for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist()) if int(c) == 3]
        people = [b for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist()) if int(c) == 0]
        for box, is_no in gt[fi]:
            total += 1
            ca = letterbox_square(pad_crop(img, box))
            pa = float(cls.predict(ca, imgsz=224, verbose=False)[0].probs.data[no_id])
            res["A"].append((is_no, pa))
            best = max(motos, key=lambda m: iou(m, box), default=None)
            if best is None or iou(best, box) < 0.2:
                continue
            found += 1
            riders = [p for p in people if overlap(p, best) > a.rider_overlap]
            ub = [min([best[0]] + [p[0] for p in riders]), min([best[1]] + [p[1] for p in riders]),
                  max([best[2]] + [p[2] for p in riders]), max([best[3]] + [p[3] for p in riders])]
            cb = letterbox_square(pad_crop(img, ub))
            pb = float(cls.predict(cb, imgsz=224, verbose=False)[0].probs.data[no_id])
            res["B"].append((is_no, pb))
            if saved < 24 and is_no:
                pair = np.hstack([cv2.resize(ca, (224, 224)), cv2.resize(cb, (224, 224))])
                cv2.putText(pair, f"GT box p={pa:.2f}", (4, 16), 0, 0.5, (0, 255, 255), 1)
                cv2.putText(pair, f"pipeline p={pb:.2f} riders={len(riders)}", (228, 16), 0, 0.5, (0, 255, 255), 1)
                cv2.imwrite(str(out / f"pair_{saved:02d}.jpg"), pair)
                saved += 1

    def rep(rows, name):
        t = np.array([x[0] for x in rows]); p = np.array([x[1] for x in rows]) >= 0.5
        tp, fp, fn = int((p & t).sum()), int((p & ~t).sum()), int((~p & t).sum())
        print(f"{name}: n={len(rows)} acc={float((p == t).mean()):.3f} "
              f"no_helmet P={tp / max(1, tp + fp):.3f} R={tp / max(1, tp + fn):.3f}  "
              f"mean p(no_helmet) on true no_helmet={np.mean([x[1] for x in rows if x[0]]):.2f}")

    print(f"C. detection: YOLO motorcycle found for {found}/{total} labelled motorcycle boxes ({found / max(1, total):.0%})")
    rep(res["A"], "A. GT-box crops      ")
    rep(res["B"], "B. pipeline crops    ")
    print("examples:", out)


if __name__ == "__main__":
    main()
