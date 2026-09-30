"""Train and evaluate the helmet classifier locally (CPU or GPU).

    python train_helmet.py --data ../data/datasets/helmet_cls --model yolo11n-cls.pt --epochs 25

Resumable: if a previous run was interrupted, running the same command again continues from
runs/helmet/cls/weights/last.pt (the last completed epoch) instead of starting over. If that run
already finished, training is skipped and only evaluation/export runs. Pass --fresh to restart.

Parallelism: data loading/augmentation runs in --workers background processes (overlapping with
the model), decoded images are cached in RAM, and PyTorch uses --threads intra-op threads.

Writes backend/models/helmet_cls.pt and helmet_cls_metrics.json (crop- and track-level test
metrics; track level = mean no_helmet probability over all crops of one motorcycle, which is
closer to how RoadGuard votes per track).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
RUN_DIR = BACKEND / "runs" / "helmet" / "cls"


def report(truth, prob, thr=0.5) -> dict:
    truth, pred = np.array(truth, bool), np.array(prob) >= thr
    tp, fp = int((pred & truth).sum()), int((pred & ~truth).sum())
    fn, tn = int((~pred & truth).sum()), int((~pred & ~truth).sum())
    prec, rec = tp / max(1, tp + fp), tp / max(1, tp + fn)
    spec = tn / max(1, tn + fp)
    return {"n": len(truth), "accuracy": round((tp + tn) / max(1, len(truth)), 4),
            "no_helmet_precision": round(prec, 4), "no_helmet_recall": round(rec, 4),
            "no_helmet_f1": round(2 * prec * rec / max(1e-9, prec + rec), 4),
            "helmet_recall": round(spec, 4), "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def evaluate(weights: Path, data: Path, imgsz: int, device: str) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    no_id = next(k for k, v in model.names.items() if v == "no_helmet")
    y, p, tracks = [], [], defaultdict(list)
    for cls in ("helmet", "no_helmet"):
        files = sorted((data / "test" / cls).glob("*.jpg"))
        for i in range(0, len(files), 128):
            chunk = files[i:i + 128]
            for f, r in zip(chunk, model.predict([str(x) for x in chunk], imgsz=imgsz, device=device, verbose=False)):
                prob = float(r.probs.data[no_id])
                y.append(cls == "no_helmet")
                p.append(prob)
                tracks[f.stem.rsplit("_", 1)[0]].append((cls == "no_helmet", prob))
    out = {"crops": report(y, p),
           "tracks": report([v[0][0] for v in tracks.values()], [float(np.mean([q for _, q in v])) for v in tracks.values()])}
    # threshold sweep at track level, to help pick rules.helmet.min_conf / voting behaviour
    out["track_threshold_sweep"] = {
        str(t): report([v[0][0] for v in tracks.values()], [float(np.mean([q for _, q in v])) for v in tracks.values()], t)
        for t in (0.3, 0.4, 0.5, 0.6, 0.7)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=BACKEND / "data/datasets/helmet_cls")
    ap.add_argument("--model", default="yolo11n-cls.pt")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--workers", type=int, default=-1, help="data-loader processes (-1 = auto)")
    ap.add_argument("--threads", type=int, default=0, help="PyTorch intra-op threads (0 = auto)")
    ap.add_argument("--cache", default="ram", choices=["ram", "disk", "none"])
    ap.add_argument("--fresh", action="store_true", help="ignore any previous run and start from scratch")
    a = ap.parse_args()

    import torch
    from ultralytics import YOLO

    cores = os.cpu_count() or 4
    if a.workers < 0:  # auto: a few loader processes, leave the rest of the cores to the model
        a.workers = max(2, min(4, cores // 3))
    threads = a.threads or max(2, cores - a.workers)
    torch.set_num_threads(threads)
    print(f"cpu cores {cores}: {a.workers} data-loader workers, {threads} torch threads, cache={a.cache}", flush=True)

    data = a.data.resolve()
    for split in ("train", "val", "test"):
        counts = {c: len(list((data / split / c).glob("*.jpg"))) for c in ("helmet", "no_helmet")}
        print(split, counts, flush=True)

    t0 = time.time()
    last = RUN_DIR / "weights" / "last.pt"
    best = RUN_DIR / "weights" / "best.pt"
    state = "fresh"
    if last.exists() and not a.fresh:
        ckpt = torch.load(last, map_location="cpu", weights_only=False)
        # Ultralytics sets epoch=-1 (and drops the optimizer) once a run has completed.
        state = "finished" if ckpt.get("epoch", -1) == -1 or ckpt.get("optimizer") is None else "resume"
        if state == "resume":
            print(f"resuming from {last} (completed epoch {ckpt['epoch'] + 1})", flush=True)

    cache = False if a.cache == "none" else a.cache
    if state == "resume":
        YOLO(str(last)).train(resume=True, workers=a.workers, cache=cache, device=a.device)
    elif state == "fresh":
        YOLO(a.model).train(
            data=str(data), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=a.device,
            workers=a.workers, cache=cache,
            # scale=0.1 → RandomResizedCrop keeps 90–100% of the (letterboxed) crop so heads stay in view;
            # no random erasing for the same reason.
            patience=8, cos_lr=True, dropout=0.1, fliplr=0.5, hsv_v=0.4, scale=0.1, erasing=0.0, seed=0, deterministic=True,
            project=str(RUN_DIR.parent), name=RUN_DIR.name, exist_ok=True, plots=True,
        )
    else:
        print(f"previous run in {RUN_DIR} already finished; evaluating best.pt (use --fresh to retrain)", flush=True)
    metrics = evaluate(best, data, a.imgsz, a.device)
    metrics.update({"model": a.model, "imgsz": a.imgsz, "epochs": a.epochs, "train_minutes": round((time.time() - t0) / 60, 1),
                    "dataset": "HELMET (osf.io/4pwj8, CC BY 4.0) — frame-budgeted subset" })
    (BACKEND / "models").mkdir(exist_ok=True)
    shutil.copy(best, BACKEND / "models" / "helmet_cls.pt")
    (BACKEND / "models" / "helmet_cls_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: metrics[k] for k in ("crops", "tracks", "train_minutes")}, indent=2))
    print("saved", BACKEND / "models" / "helmet_cls.pt")


if __name__ == "__main__":
    main()
