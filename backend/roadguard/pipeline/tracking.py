"""Class-grouped multi-object tracking.

Ultralytics' ByteTrack associates boxes by IoU regardless of class. On two-wheelers the rider's
person box overlaps the motorcycle box heavily, so a single tracker lets riders "steal" motorcycle
track IDs (and vice versa). Here detection runs once per frame and people and vehicles are
tracked by separate ByteTrack instances.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import YAML, IterableSimpleNamespace
from ultralytics.utils.checks import check_yaml


class GroupedTracker:
    def __init__(self, tracker_cfg: str, groups: Iterable[Iterable[int]]):
        cfg = IterableSimpleNamespace(**YAML.load(check_yaml(tracker_cfg)))
        if cfg.tracker_type != "bytetrack":
            raise ValueError(f"only bytetrack is supported by GroupedTracker, got {cfg.tracker_type}")
        self.groups = [np.array(sorted(g)) for g in groups]
        self.trackers = [BYTETracker(args=cfg) for _ in self.groups]
        # STrack IDs come from one shared counter, so IDs are unique across groups; remap anyway so
        # a counter reset by another job can never merge two of this job's tracks.
        self._ids: dict[tuple[int, int], int] = {}

    def update(self, boxes, img: np.ndarray) -> list[tuple[int, int, float, tuple[float, float, float, float]]]:
        """boxes: ultralytics Boxes (numpy). Returns [(track_id, cls_id, conf, (x1,y1,x2,y2))]."""
        out = []
        cls = boxes.cls.astype(int)
        for gi, (ids, trk) in enumerate(zip(self.groups, self.trackers)):
            # Every tracker is updated each frame (even with no detections) so lost tracks age out.
            rows = trk.update(boxes[np.isin(cls, ids)], img)
            for x1, y1, x2, y2, tid, conf, c, _ in rows:
                key = (gi, int(tid))
                if key not in self._ids:
                    self._ids[key] = len(self._ids) + 1
                out.append((self._ids[key], int(c), float(conf), (float(x1), float(y1), float(x2), float(y2))))
        return out
