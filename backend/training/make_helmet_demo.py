"""Build a demo video from HELMET test-split clips (never seen in training).

    python make_helmet_demo.py Mandalay_2_53 Mandalay_2_156 ... --out ../data/samples/helmet_demo_mandalay.mp4

Also writes <out>.groundtruth.json with per-clip counts of motorcycles with/without helmets,
so detector output can be compared against the labels.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from fetch_helmet_subset import PARTS
from remote_zip import RemoteZip

DATA = Path(__file__).resolve().parent.parent / "data" / "datasets" / "helmet_osf"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-height", type=int, default=80)
    a = ap.parse_args()

    split = {r["video_id"]: r["Set"] for r in csv.DictReader(open(DATA / "data_split.csv"))}
    for c in a.clips:
        if split.get(c) != "test":
            raise SystemExit(f"{c} is not in the test split ({split.get(c)}); refusing to demo on training data")

    # locate each clip's frames in the part zips
    members: dict[str, list[tuple[RemoteZip, str]]] = defaultdict(list)
    for part, oid in PARTS.items():
        if all(members.get(c) for c in a.clips):
            break
        z = RemoteZip(f"https://osf.io/download/{oid}/")
        for name in z.members:
            bits = name.split("/")
            if len(bits) >= 3 and bits[-2] in a.clips and bits[-1].endswith(".jpg"):
                members[bits[-2]].append((z, name))
        print(f"indexed {part}", {c: len(members[c]) for c in a.clips}, flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(a.out), cv2.VideoWriter_fourcc(*"mp4v"), 10, (1920, 1080))
    gt = {}
    for clip in a.clips:
        items = sorted(members[clip], key=lambda m: int(Path(m[1]).stem))
        z = items[0][0]
        for name, data in z.read_many([n for _, n in items], workers=8):
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
            if img is None:
                raise SystemExit(f"failed to fetch {name}")
            writer.write(cv2.resize(img, (1920, 1080)) if img.shape[:2] != (1080, 1920) else img)
        print(f"wrote {clip}: {len(items)} frames", flush=True)
        last, big = {}, defaultdict(float)
        for r in csv.DictReader(open(next(DATA.rglob(f"annotation/**/{clip}.csv")))):
            last[r["track_id"]] = r["label"]
            big[r["track_id"]] = max(big[r["track_id"]], float(r["h"]))
        judged = [t for t in last if big[t] >= a.min_height]
        gt[clip] = {"motorcycles_labelled": len(last), f"judgeable_h>={a.min_height}px": len(judged),
                    "no_helmet": sum(1 for t in judged if "NoHelmet" in last[t]),
                    "helmet": sum(1 for t in judged if "NoHelmet" not in last[t])}
    writer.release()
    gt["_note"] = ("HELMET dataset test split (osf.io/4pwj8, CC BY 4.0), 10 fps; clips concatenated in order, "
                   "100 frames (10 s) each.")
    Path(str(a.out) + ".groundtruth.json").write_text(json.dumps(gt, indent=2))
    print(json.dumps(gt, indent=2))


if __name__ == "__main__":
    main()
