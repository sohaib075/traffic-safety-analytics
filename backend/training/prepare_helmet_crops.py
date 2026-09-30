"""Build a YOLO classification dataset of motorcycle crops from the HELMET dataset.

HELMET dataset — Lin & Siebert, "Helmet use detection of tracked motorcycles using CNN-based
multi-task learning", IEEE Access 2020. https://osf.io/4pwj8/ — CC BY 4.0.
910 ten-second clips (1920×1080, 10 fps) from 12 sites in Myanmar, 10,006 tracked motorcycles
with position-specific helmet labels such as ``DHelmetP1NoHelmet``.

Each annotated box covers the motorcycle *and* its riders, which matches the crop RoadGuard
builds from a tracked motorcycle plus overlapping rider boxes. Classes:
    helmet     every rider on the motorcycle wears a helmet
    no_helmet  at least one rider does not

The official per-clip split (data_split.csv) is used, so frames of one clip never leak across
train/val/test. Consecutive frames are near-duplicates, so each track is sampled every
``--stride`` frames.

Usage:
    python prepare_helmet_crops.py --images <dir with part_*/clip/N.jpg> \
        --annotations <dir with clip.csv> --split data_split.csv --out helmet_cls
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

import cv2

SPLITS = {"training": "train", "validation": "val", "test": "test"}


def letterbox_square(img, fill: int = 114):
    """Pad to a square (content centred) so YOLO-cls's resize + centre-crop never cuts anything.

    Rider+motorcycle crops are tall; a plain centre crop would remove the top of the image,
    which is exactly where the riders' heads are. RoadGuard applies the same padding at inference.
    """
    h, w = img.shape[:2]
    s = max(h, w)
    top, left = (s - h) // 2, (s - w) // 2
    return cv2.copyMakeBorder(img, top, s - h - top, left, s - w - left, cv2.BORDER_CONSTANT, value=(fill, fill, fill))


def label_of(raw: str) -> str:
    return "no_helmet" if "NoHelmet" in raw else "helmet"


def riders(raw: str) -> int:
    return len(re.findall(r"(?:D|P\d)(?:Helmet|NoHelmet)", raw))


def build(images: Path, annotations: Path, split_csv: Path, out: Path,
          stride: int = 5, min_height: int = 48, pad: float = 0.08, max_per_track: int = 12) -> dict:
    split_of = {r["video_id"]: SPLITS[r["Set"].strip().lower()] for r in csv.DictReader(open(split_csv))}
    clip_dirs = {p.name: p for p in images.rglob("*") if p.is_dir() and p.name in split_of}
    stats: dict[str, Counter] = defaultdict(Counter)
    missing = 0
    for clip, cdir in sorted(clip_dirs.items()):
        ann = annotations / f"{clip}.csv"
        if not ann.exists():
            ann = next(annotations.rglob(f"{clip}.csv"), None)
        if ann is None:
            continue
        split = split_of[clip]
        by_track: dict[str, list] = defaultdict(list)
        for r in csv.DictReader(open(ann)):
            by_track[r["track_id"]].append(r)
        frame_cache: dict[int, object] = {}
        for tid, rows in by_track.items():
            rows.sort(key=lambda r: int(r["frame_id"]))
            kept = 0
            last = -10**9
            for r in rows:
                f = int(r["frame_id"])
                if f - last < stride or kept >= max_per_track:
                    continue
                x, y, w, h = (float(r[k]) for k in "xywh")
                if h < min_height:
                    continue
                if f not in frame_cache:
                    p = cdir / f"{f}.jpg"
                    if not p.exists():
                        p = cdir / f"{f:02d}.jpg"
                    frame_cache[f] = cv2.imread(str(p)) if p.exists() else None
                img = frame_cache[f]
                if img is None:
                    missing += 1
                    continue
                H, W = img.shape[:2]
                px, py = w * pad, h * pad
                x1, y1 = int(max(0, x - px)), int(max(0, y - py * 1.5))  # a bit more headroom
                x2, y2 = int(min(W, x + w + px)), int(min(H, y + h + py))
                crop = img[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                cls = label_of(r["label"])
                d = out / split / cls
                d.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(d / f"{clip}_{tid}_{f:03d}.jpg"), letterbox_square(crop), [cv2.IMWRITE_JPEG_QUALITY, 92])
                stats[split][cls] += 1
                stats[split][f"riders_{riders(r['label'])}"] += 1
                kept += 1
                last = f
            if kept:
                stats[split]["tracks"] += 1
        stats["_"]["clips"] += 1
    stats["_"]["missing_frames"] = missing
    (out / "ATTRIBUTION.txt").parent.mkdir(parents=True, exist_ok=True)
    (out / "ATTRIBUTION.txt").write_text(
        "Crops derived from the HELMET dataset (Lin & Siebert, IEEE Access 2020), https://osf.io/4pwj8/, "
        "licensed CC BY 4.0. Labels collapsed to helmet / no_helmet per motorcycle.\n")
    return {k: dict(v) for k, v in stats.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--split", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("helmet_cls"))
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--min-height", type=int, default=48)
    a = ap.parse_args()
    for k, v in build(a.images, a.annotations, a.split, a.out, a.stride, a.min_height).items():
        print(k, v)
