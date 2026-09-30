import numpy as np
from ultralytics.engine.results import Boxes

from roadguard.pipeline.tracking import GroupedTracker

PERSON, MOTO = 0, 3


def boxes(rows):
    return Boxes(np.array(rows, dtype=np.float32).reshape(-1, 6), (720, 1280))


def test_rider_and_motorcycle_keep_separate_ids():
    trk = GroupedTracker("bytetrack.yaml", [[PERSON], [MOTO]])
    seen = {}
    for f in range(12):
        dx = 12 * f
        out = trk.update(boxes([
            [500 + dx, 400, 580 + dx, 520, 0.9, MOTO],    # motorcycle
            [505 + dx, 330, 575 + dx, 480, 0.9, PERSON],  # rider, heavily overlapping it
        ]), np.zeros((720, 1280, 3), np.uint8))
        for tid, cls, _, _ in out:
            seen.setdefault(tid, set()).add(cls)
    assert len(seen) == 2, seen  # exactly two identities over the whole sequence
    assert all(len(c) == 1 for c in seen.values())  # and neither ever switches class


def test_empty_frames_are_fine():
    trk = GroupedTracker("bytetrack.yaml", [[PERSON], [MOTO]])
    assert trk.update(boxes([]), np.zeros((10, 10, 3), np.uint8)) == []
