"""Score a RoadGuard run on the HELMET demo video against the dataset's ground truth.

Each RoadGuard motorcycle track is matched to the ground-truth motorcycle whose labelled box
contains the track's foot point in most of its sampled frames. Then:
  * flagged   = a helmet_violation incident was raised for the track (what an operator sees)
  * voted     = the track received helmet votes (its per-track majority label)

    python eval_helmet_demo.py --job 4 --clips Mandalay_2_53 Mandalay_2_156 Mandalay_2_108 Mandalay_2_183
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ANN = BACKEND / "data" / "datasets" / "helmet_osf"
W, H, FPS, CLIP_FRAMES = 1920, 1080, 10, 100


def load_gt(clips, min_h):
    boxes = defaultdict(dict)  # (clip_idx, frame) -> {gt_key: (x1,y1,x2,y2)}
    label, height = {}, defaultdict(float)
    for ci, clip in enumerate(clips):
        for r in csv.DictReader(open(next(ANN.rglob(f"annotation/**/{clip}.csv")))):
            key = f"{clip}:{r['track_id']}"
            x, y, w, h = (float(r[k]) for k in "xywh")
            boxes[(ci, int(r["frame_id"]))][key] = (x - 0.1 * w, y - 0.1 * h, x + 1.1 * w, y + 1.1 * h)
            label[key] = "no_helmet" if "NoHelmet" in r["label"] else "helmet"
            height[key] = max(height[key], h)
    judge = {k for k in label if height[k] >= min_h}
    return boxes, label, judge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", type=int, required=True)
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--min-height", type=int, default=80)
    a = ap.parse_args()

    boxes, label, judge = load_gt(a.clips, a.min_height)
    db = sqlite3.connect(BACKEND / "data" / "roadguard.db")
    tracks = db.execute("select track_id, path, helmet from tracks where job_id=? and cls='motorcycle'", (a.job,)).fetchall()
    flagged = {tid for (tids,) in db.execute("select track_ids from incidents where job_id=? and type='helmet_violation'", (a.job,))
               for tid in json.loads(tids)[:1]}

    matched: dict[str, dict] = {}
    unmatched = 0
    for tid, path, helmet in tracks:
        votes = Counter()
        for t, nx, ny in json.loads(path):
            frame_global = int(round(t * FPS))
            ci, f = divmod(frame_global, CLIP_FRAMES)
            px, py = nx * W, ny * H
            for key, (x1, y1, x2, y2) in boxes.get((ci, f + 1), {}).items():
                if x1 <= px <= x2 and y1 <= py <= y2:
                    votes[key] += 1
        if not votes:
            unmatched += 1
            continue
        key, n = votes.most_common(1)[0]
        prev = matched.get(key)
        if prev is None or n > prev["n"]:  # keep the best-overlapping track per GT motorcycle
            matched[key] = {"n": n, "tid": tid, "vote": helmet, "flag": tid in flagged}

    def score(pred_of):
        tp = fp = fn = tn = abstain = 0
        for key in judge:
            m = matched.get(key)
            pred = pred_of(m) if m else None
            if pred is None:
                abstain += 1
                continue
            gt_no = label[key] == "no_helmet"
            if pred == "no_helmet":
                tp += gt_no; fp += not gt_no
            else:
                fn += gt_no; tn += not gt_no
        n = tp + fp + fn + tn
        return {"judged": n, "abstained_or_unmatched": abstain, "accuracy": round((tp + tn) / max(1, n), 3),
                "no_helmet_precision": round(tp / max(1, tp + fp), 3), "no_helmet_recall": round(tp / max(1, tp + fn), 3),
                "tp": tp, "fp": fp, "fn": fn, "tn": tn}

    gt_counts = Counter(label[k] for k in judge)
    out = {
        "ground_truth_motorcycles": len(judge), "ground_truth": dict(gt_counts),
        "roadguard_motorcycle_tracks": len(tracks), "tracks_matched_to_gt": len(matched), "tracks_unmatched": unmatched,
        "gt_motorcycles_with_a_track": sum(1 for k in judge if k in matched),
        "helmet_incidents_raised": len(flagged),
        # operator view: an incident means "no_helmet", matched but no incident means "helmet"
        "incidents_vs_truth": score(lambda m: "no_helmet" if m["flag"] else "helmet"),
        # per-track majority vote (includes tracks with fewer votes than min_votes)
        "track_votes_vs_truth": score(lambda m: m["vote"]),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
