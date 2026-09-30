"""Download a frame-budgeted subset of the HELMET dataset and write classification crops.

For slow links where streaming all ~28 GB is impractical. Frames are chosen to cover as many
distinct motorcycle tracks as possible, spread round-robin over all 910 clips (so every site
and split is represented), and only those frames are fetched from the remote zips via HTTP
range requests. Output layout matches prepare_helmet_crops.py:
    <out>/{train,val,test}/{helmet,no_helmet}/<clip>_<track>_<frame>.jpg

Resumable: frames whose crops already exist are skipped.

    python fetch_helmet_subset.py --annotations ../data/datasets/helmet_osf/annotation \
        --split ../data/datasets/helmet_osf/data_split.csv --out ../data/datasets/helmet_cls --budget 2200
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from prepare_helmet_crops import SPLITS, label_of, letterbox_square
from remote_zip import RemoteZip

PARTS = {"part_1": "452nq", "part_2": "muzgb", "part_3": "9dmw3", "part_4": "39ynb",
         "part_5": "v3rch", "part_6": "jyg9s", "part_7": "6h5ka"}


def plan(annotations: Path, split_of: dict, budget: int, min_height: int, seed: int = 0):
    """Return [(clip, frame, [rows])] chosen round-robin by new-track coverage."""
    per_clip: dict[str, list[tuple[int, list]]] = {}
    for ann in sorted(annotations.rglob("*.csv")):
        clip = ann.stem
        if clip not in split_of:
            continue
        frames: dict[int, list] = defaultdict(list)
        for r in csv.DictReader(open(ann)):
            if float(r["h"]) >= min_height:
                frames[int(r["frame_id"])].append(r)
        if frames:
            per_clip[clip] = sorted(frames.items())
    covered: dict[str, set] = defaultdict(set)
    used: dict[str, set] = defaultdict(set)
    chosen = []
    clips = sorted(per_clip)
    random.Random(seed).shuffle(clips)
    while len(chosen) < budget:
        progress = False
        for clip in clips:
            if len(chosen) >= budget:
                break
            best, best_gain = None, 0
            for f, rows in per_clip[clip]:
                if f in used[clip] or any(abs(f - u) < 5 for u in used[clip]):
                    continue
                gain = sum(1 for r in rows if r["track_id"] not in covered[clip]) * 10 + len(rows)
                if gain > best_gain:
                    best, best_gain = (f, rows), gain
            if best is None:
                continue
            f, rows = best
            used[clip].add(f)
            covered[clip].update(r["track_id"] for r in rows)
            chosen.append((clip, f, rows))
            progress = True
        if not progress:
            break
    return chosen


def crop(img, r, pad=0.08):
    H, W = img.shape[:2]
    x, y, w, h = (float(r[k]) for k in "xywh")
    px, py = w * pad, h * pad
    x1, y1 = int(max(0, x - px)), int(max(0, y - py * 1.5))
    x2, y2 = int(min(W, x + w + px)), int(min(H, y + h + py))
    return img[y1:y2, x1:x2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--split", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--budget", type=int, default=2200, help="number of frames to download")
    ap.add_argument("--min-height", type=int, default=48)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    split_of = {r["video_id"]: SPLITS[r["Set"].strip().lower()] for r in csv.DictReader(open(a.split))}
    chosen = plan(a.annotations, split_of, a.budget, a.min_height)
    print(f"planned {len(chosen)} frames covering "
          f"{len({(c, r['track_id']) for c, _, rows in chosen for r in rows})} tracks", flush=True)

    zips = {}
    member_of = {}
    for part, oid in PARTS.items():
        z = RemoteZip(f"https://osf.io/download/{oid}/")
        zips[part] = z
        for name in z.members:
            bits = name.split("/")
            if len(bits) >= 3 and bits[-1].endswith(".jpg"):
                member_of[(bits[-2], int(Path(bits[-1]).stem))] = (part, name)
        print(f"indexed {part}: {len(z.members)} files", flush=True)

    todo = []
    for clip, f, rows in chosen:
        key = member_of.get((clip, f))
        if key is None:
            continue
        split = split_of[clip]
        outs = [a.out / split / label_of(r["label"]) / f"{clip}_{r['track_id']}_{f:03d}.jpg" for r in rows]
        if all(o.exists() for o in outs):
            continue
        todo.append((key, rows, outs))
    print(f"{len(todo)} frames to fetch", flush=True)

    stats = Counter()
    t0, nbytes = time.time(), 0
    by_part = defaultdict(list)
    for item in todo:
        by_part[item[0][0]].append(item)
    for part, items in by_part.items():
        z = zips[part]
        names = [it[0][1] for it in items]
        for (name, data), (_, rows, outs) in zip(z.read_many(names, workers=a.workers), items):
            if data is None:
                stats["failed"] += 1
                continue
            nbytes += len(data)
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                stats["failed"] += 1
                continue
            for r, o in zip(rows, outs):
                c = crop(img, r)
                if c.size:
                    o.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(o), letterbox_square(c), [cv2.IMWRITE_JPEG_QUALITY, 92])
                    stats[f"{o.parent.parent.name}/{o.parent.name}"] += 1
            stats["frames"] += 1
            if stats["frames"] % 50 == 0:
                dt = time.time() - t0
                print(f"{stats['frames']}/{len(todo)} frames  {nbytes / 1e6:.0f} MB  {nbytes / 1e6 / dt:.2f} MB/s  "
                      f"eta {(len(todo) - stats['frames']) * dt / stats['frames'] / 60:.0f} min", flush=True)
    (a.out / "ATTRIBUTION.txt").write_text(
        "Crops derived from the HELMET dataset (Lin & Siebert, IEEE Access 2020), https://osf.io/4pwj8/, "
        "licensed CC BY 4.0. Labels collapsed to helmet / no_helmet per motorcycle.\n")
    print("done", json.dumps(dict(stats)), flush=True)


if __name__ == "__main__":
    main()
