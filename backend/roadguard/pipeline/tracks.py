"""Trajectory state for tracked road users."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..camera_config import PERSON_CLASS, VEHICLE_CLASSES
from .geometry import SceneGeometry

# Approximate footprint radius in metres, used for conflict clearance.
CLASS_RADIUS_M = {
    "person": 0.4,
    "bicycle": 0.8,
    "motorcycle": 1.0,
    "car": 2.2,
    "bus": 5.5,
    "truck": 4.5,
}


@dataclass
class Observation:
    t: float
    frame: int
    px: float  # foot point (bottom-centre of box) in pixels
    py: float
    g: np.ndarray  # ground-plane position (m)
    bbox: tuple[float, float, float, float]
    conf: float


@dataclass
class Track:
    track_id: int
    history: deque = field(default_factory=lambda: deque(maxlen=900))
    cls_votes: Counter = field(default_factory=Counter)
    first_t: float = 0.0
    last_t: float = 0.0
    first_frame: int = 0
    zones: list[str] = field(default_factory=list)  # ordered, de-duplicated zone visits
    path: list[tuple[float, float, float]] = field(default_factory=list)  # (t, nx, ny) sampled
    max_speed: float = 0.0
    events: list[str] = field(default_factory=list)
    helmet_votes: Counter = field(default_factory=Counter)  # head-detector mode
    helmet_probs: list = field(default_factory=list)  # classifier mode: P(no_helmet) per check
    helmet_label: Optional[str] = None  # current per-track decision
    rider_frames: int = 0  # frames in which this person overlapped a two-wheeler
    n_obs: int = 0

    @property
    def is_pedestrian(self) -> bool:
        return self.is_person and self.rider_frames < 0.3 * max(1, self.n_obs)

    @property
    def cls(self) -> str:
        return self.cls_votes.most_common(1)[0][0] if self.cls_votes else "unknown"

    @property
    def is_vehicle(self) -> bool:
        return self.cls in VEHICLE_CLASSES

    @property
    def is_person(self) -> bool:
        return self.cls == PERSON_CLASS

    @property
    def last(self) -> Observation:
        return self.history[-1]

    @property
    def radius(self) -> float:
        return CLASS_RADIUS_M.get(self.cls, 1.5)

    def window(self, seconds: float) -> list[Observation]:
        if not self.history:
            return []
        t_end = self.history[-1].t
        out = []
        for ob in reversed(self.history):
            if t_end - ob.t > seconds:
                break
            out.append(ob)
        out.reverse()
        return out

    def velocity(self, seconds: float = 0.6) -> np.ndarray:
        """Ground-plane velocity (m/s) from a least-squares fit over the recent window."""
        obs = self.window(seconds)
        if len(obs) < 3:
            return np.zeros(2)
        t = np.array([o.t for o in obs])
        g = np.stack([o.g for o in obs])
        t = t - t.mean()
        denom = float(t @ t)
        if denom < 1e-9:
            return np.zeros(2)
        return (t @ (g - g.mean(axis=0))) / denom

    def speed(self, seconds: float = 0.6) -> float:
        return float(np.linalg.norm(self.velocity(seconds)))

    def image_displacement(self, seconds: float) -> Optional[np.ndarray]:
        obs = self.window(seconds)
        if len(obs) < 2:
            return None
        return np.array([obs[-1].px - obs[0].px, obs[-1].py - obs[0].py])


class TrackManager:
    """Owns all live tracks; retires tracks that have not been seen for `lost_s` seconds."""

    def __init__(self, geom: SceneGeometry, lost_s: float = 2.0, path_sample_s: float = 0.25):
        self.geom = geom
        self.lost_s = lost_s
        self.path_sample_s = path_sample_s
        self.tracks: dict[int, Track] = {}

    def update(self, t: float, frame: int, dets: list[tuple[int, str, float, tuple]]) -> list[Track]:
        """dets: (track_id, cls, conf, (x1,y1,x2,y2)). Returns tracks retired this step."""
        for tid, cls, conf, box in dets:
            x1, y1, x2, y2 = box
            px, py = (x1 + x2) / 2.0, y2
            tr = self.tracks.get(tid)
            if tr is None:
                tr = Track(track_id=tid, first_t=t, first_frame=frame)
                self.tracks[tid] = tr
            tr.cls_votes[cls] += 1
            tr.n_obs += 1
            tr.last_t = t
            tr.history.append(Observation(t, frame, px, py, self.geom.to_ground(px, py), box, conf))
            if not tr.path or t - tr.path[-1][0] >= self.path_sample_s:
                tr.path.append((round(t, 2), round(px / self.geom.width, 4), round(py / self.geom.height, 4)))
            if len(tr.history) >= 5:
                tr.max_speed = max(tr.max_speed, tr.speed())
        retired = [tr for tr in self.tracks.values() if t - tr.last_t > self.lost_s]
        for tr in retired:
            del self.tracks[tr.track_id]
        return retired

    def active(self, max_age_s: float = 0.25) -> list[Track]:
        """Tracks observed very recently (i.e. visible now)."""
        if not self.tracks:
            return []
        now = max(tr.last_t for tr in self.tracks.values())
        return [tr for tr in self.tracks.values() if now - tr.last_t <= max_age_s]

    def flush(self) -> list[Track]:
        out = list(self.tracks.values())
        self.tracks.clear()
        return out
