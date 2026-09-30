"""Where do labelled motorcycles get lost: detection, or tracking?

Runs the same YOLO + ByteTrack as the pipeline over the demo video and, for every labelled
motorcycle (HELMET ground truth), reports how many of its frames had a matching detection and
how many different track IDs covered it.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
ANN = BACKEND / "data" / "datasets" / "helmet_osf"


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(BACKEND / "data/samples/helmet_demo_mandalay.mp4"))
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--tracker", default="bytetrack.yaml")
    ap.add_argument("--model", default=str(BACKEND / "yolov8n.pt"))
    a = ap.parse_args()
    from ultralytics import YOLO

    gt = defaultdict(list)  # frame -> [(key, box)]
    frames_of = Counter()
    for ci, clip in enumerate(a.clips):
        for r in csv.DictReader(open(next(ANN.rglob(f"annotation/**/{clip}.csv")))):
            x, y, w, h = (float(r[k]) for k in "xywh")
            if h >= 80:
                key = f"{clip}:{r['track_id']}"
                gt[ci * 100 + int(r["frame_id"]) - 1].append((key, (x, y, x + w, y + h)))
                frames_of[key] += 1

    model = YOLO(a.model)
    hit = Counter()
    ids = defaultdict(Counter)
    for fi, r in enumerate(model.track(a.video, stream=True, persist=True, tracker=a.tracker, classes=[3],
                                       conf=a.conf, imgsz=a.imgsz, verbose=False)):
        dets = []
        if r.boxes is not None and len(r.boxes):
            tids = r.boxes.id.int().tolist() if r.boxes.id is not None else [None] * len(r.boxes)
            dets = list(zip(r.boxes.xyxy.tolist(), tids))
        for key, box in gt.get(fi, []):
            best = max(dets, key=lambda d: iou(d[0], box), default=None)
            if best and iou(best[0], box) >= 0.2:
                hit[key] += 1
                if best[1] is not None:
                    ids[key][best[1]] += 1

    keys = list(frames_of)
    det_rate = np.array([hit[k] / frames_of[k] for k in keys])
    n_ids = np.array([len(ids[k]) for k in keys])
    longest = np.array([max(ids[k].values(), default=0) for k in keys])
    print(f"labelled motorcycles: {len(keys)}  (frames each: median {int(np.median([frames_of[k] for k in keys]))})")
    print(f"detected in >=1 frame: {int((det_rate > 0).sum())}   in >=50% of frames: {int((det_rate >= 0.5).sum())}")
    print(f"median per-motorcycle detection rate: {np.median(det_rate):.2f}")
    print(f"track IDs per motorcycle: 0 -> {int((n_ids == 0).sum())}, 1 -> {int((n_ids == 1).sum())}, "
          f"2+ -> {int((n_ids >= 2).sum())} (fragmented)")
    print(f"longest single-ID coverage >= 4 frames (enough for 4 checks at 10 fps/0.2 s ≈ 7 frames?): "
          f"{int((longest >= 4).sum())}; >= 8 frames: {int((longest >= 8).sum())}")


if __name__ == "__main__":
    main()
