"""Rule-based event detection on top of tracked trajectories.

Every detector reports *potential* events — they are indicators for human review, not
confirmed violations or accidents.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..camera_config import CameraConfig
from .geometry import SceneGeometry, point_in_poly, segments_intersect, side_of_line, unit
from .signals import RED, SignalMonitor
from .tracks import Track

EVENT_LABELS = {
    "near_miss": "Potential Near-Miss",
    "ped_conflict": "Potential Pedestrian Conflict",
    "red_light": "Red-Light Event",
    "wrong_way": "Potential Wrong-Way",
    "illegal_stop": "Potential Illegal Stopping",
    "congestion": "Congestion",
    "helmet_violation": "Potential Helmet Violation",
}


@dataclass
class Event:
    type: str
    severity: str  # low | medium | high
    t: float  # seconds from video start
    frame: int
    track_ids: list[int]
    classes: list[str]
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    confidence: float = 0.0
    metrics: dict = field(default_factory=dict)
    description: str = ""

    @property
    def label(self) -> str:
        return EVENT_LABELS.get(self.type, self.type)


def _ttc_to_clearance(p: np.ndarray, v: np.ndarray, clearance: float) -> Optional[float]:
    """Time until |p + v t| first equals `clearance` (None if it never does going forward)."""
    a = float(v @ v)
    b = 2.0 * float(p @ v)
    c = float(p @ p) - clearance * clearance
    if a < 1e-9 or c <= 0:  # static relative motion, or already overlapping (unreliable)
        return None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - math.sqrt(disc)) / (2 * a)
    return t if t > 0 else None


def _severity_from_ttc(ttc: float, threshold: float) -> str:
    if ttc < threshold / 3:
        return "high"
    if ttc < threshold * 2 / 3:
        return "medium"
    return "low"


class RuleEngine:
    def __init__(self, cfg: CameraConfig, geom: SceneGeometry):
        self.cfg = cfg
        self.geom = geom
        self.zone_px = {z.id: geom.poly_px(z.polygon) for z in cfg.zones}
        self.lane_px = {l.id: geom.poly_px(l.polygon) for l in cfg.lanes}
        self.signals = {s.id: SignalMonitor(s, geom.width, geom.height) for s in cfg.signals}
        self.signal_state: dict[str, str] = {}

        self.track_zones: dict[int, set[str]] = {}
        self._prev_foot: dict[int, tuple[float, float]] = {}
        self._pair_hits: dict[tuple, int] = {}
        self._pair_last: dict[tuple, float] = {}
        self._ww_hits: dict[int, int] = {}
        self._ww_last_eval: dict[int, float] = {}
        self._fired: set[tuple] = set()  # (type, track_id) one-shot events
        self._stationary_since: dict[int, float] = {}
        self._congested_since: dict[str, float] = {}
        self._congestion_last: dict[str, float] = {}
        # counting-line tallies: line_id -> {cls: {"fwd": n, "back": n}}
        self.line_counts: dict[str, dict[str, dict[str, int]]] = {}
        # per-zone live metrics, refreshed every frame
        self.zone_live: dict[str, dict] = {}

    # ------------------------------------------------------------------ helpers
    def _zone_of(self, tr: Track) -> tuple[Optional[str], Optional[str]]:
        zones = self.track_zones.get(tr.track_id) or set()
        # Prefer the most specific zone type for labelling.
        order = {"crosswalk": 0, "no_stopping": 1, "intersection": 2, "parking": 3, "road": 4}
        best = sorted((z for z in self.cfg.zones if z.id in zones), key=lambda z: order.get(z.type, 9))
        return (best[0].id, best[0].name) if best else (None, None)

    def _in_zones(self, tr: Track, allowed: list[str]) -> bool:
        return not allowed or bool(self.track_zones.get(tr.track_id, set()) & set(allowed))

    def _once(self, key: tuple) -> bool:
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    # ------------------------------------------------------------------ main entry
    def process(self, t: float, frame_idx: int, frame: np.ndarray, tracks: list[Track]) -> list[Event]:
        for sid, mon in self.signals.items():
            self.signal_state[sid] = mon.update(t, frame)

        for tr in tracks:
            foot = (tr.last.px, tr.last.py)
            inside = {zid for zid, poly in self.zone_px.items() if point_in_poly(foot, poly)}
            self.track_zones[tr.track_id] = inside
            for zid in inside:
                if zid not in tr.zones:
                    tr.zones.append(zid)

        events: list[Event] = []
        r = self.cfg.rules
        if r.near_miss.enabled:
            events += self._near_miss(t, frame_idx, tracks)
        if r.ped_conflict.enabled:
            events += self._ped_conflict(t, frame_idx, tracks)
        if r.wrong_way.enabled and self.cfg.lanes:
            events += self._wrong_way(t, frame_idx, tracks)
        if r.red_light.enabled and self.cfg.stop_lines:
            events += self._red_light(t, frame_idx, tracks)
        if r.illegal_stop.enabled:
            events += self._illegal_stop(t, frame_idx, tracks)
        self._update_zone_live(tracks)
        if r.congestion.enabled:
            events += self._congestion(t, frame_idx)
        self._count_lines(tracks)

        for tr in tracks:
            self._prev_foot[tr.track_id] = (tr.last.px, tr.last.py)
        for ev in events:
            for tr in tracks:
                if tr.track_id in ev.track_ids:
                    tr.events.append(ev.type)
        return events

    def forget(self, track_id: int) -> None:
        self._prev_foot.pop(track_id, None)
        self.track_zones.pop(track_id, None)
        self._ww_hits.pop(track_id, None)
        self._ww_last_eval.pop(track_id, None)
        self._stationary_since.pop(track_id, None)

    # ------------------------------------------------------------------ conflicts
    def _pair_conflict(self, t, frame_idx, a: Track, b: Track, rule, etype: str, min_speed_check) -> Optional[Event]:
        if len(a.history) < 5 or len(b.history) < 5:
            return None
        key = (etype, min(a.track_id, b.track_id), max(a.track_id, b.track_id))
        if t - self._pair_last.get(key, -1e9) < rule.cooldown_s:
            return None
        va, vb = a.velocity(), b.velocity()
        if not min_speed_check(va, vb):
            self._pair_hits.pop(key, None)
            return None
        p = b.last.g - a.last.g
        v = vb - va
        dist = float(np.linalg.norm(p))
        closing = -float(p @ v) / dist if dist > 1e-6 else 0.0
        clearance = a.radius + b.radius + rule.margin_m
        ttc = _ttc_to_clearance(p, v, clearance) if closing >= rule.min_closing_mps else None
        if ttc is None or ttc > rule.ttc_threshold_s or ttc > rule.horizon_s:
            self._pair_hits.pop(key, None)
            return None
        hits = self._pair_hits.get(key, 0) + 1
        self._pair_hits[key] = hits
        if hits < rule.confirm_frames:
            return None
        self._pair_hits.pop(key, None)
        self._pair_last[key] = t
        zid, zname = self._zone_of(a)
        if zid is None:
            zid, zname = self._zone_of(b)
        sev = _severity_from_ttc(ttc, rule.ttc_threshold_s)
        conf = min(a.last.conf, b.last.conf)
        return Event(
            type=etype,
            severity=sev,
            t=t,
            frame=frame_idx,
            track_ids=[a.track_id, b.track_id],
            classes=[a.cls, b.cls],
            zone_id=zid,
            zone_name=zname,
            confidence=round(conf, 3),
            metrics={
                "ttc_s": round(ttc, 2),
                "distance_m": round(dist, 2),
                "closing_speed_mps": round(closing, 2),
                "speed_a_mps": round(float(np.linalg.norm(va)), 2),
                "speed_b_mps": round(float(np.linalg.norm(vb)), 2),
                "calibrated": self.geom.calibrated,
            },
            description=(
                f"{a.cls.title()} #{a.track_id} and {b.cls} #{b.track_id} closing at "
                f"{closing:.1f} m/s; estimated time-to-conflict {ttc:.2f}s"
            ),
        )

    def _near_miss(self, t, frame_idx, tracks) -> list[Event]:
        rule = self.cfg.rules.near_miss
        vehicles = [tr for tr in tracks if tr.is_vehicle and self._in_zones(tr, rule.zones)]
        out = []
        for a, b in itertools.combinations(vehicles, 2):
            ev = self._pair_conflict(
                t, frame_idx, a, b, rule, "near_miss",
                lambda va, vb: max(np.linalg.norm(va), np.linalg.norm(vb)) >= rule.min_speed_mps,
            )
            if ev:
                out.append(ev)
        return out

    def _ped_conflict(self, t, frame_idx, tracks) -> list[Event]:
        rule = self.cfg.rules.ped_conflict
        vehicles = [tr for tr in tracks if tr.is_vehicle and tr.cls != "bicycle"]
        two_wheelers = [tr for tr in tracks if tr.cls in ("motorcycle", "bicycle")]
        # Riders sit on their two-wheeler: they are not pedestrians.
        people = [
            tr for tr in tracks
            if tr.is_person and self._in_zones(tr, rule.zones)
            and not any(_overlap_ratio(tr.last.bbox, m.last.bbox) > 0.3 for m in two_wheelers)
        ]
        out = []
        for veh in vehicles:
            for ped in people:
                ev = self._pair_conflict(
                    t, frame_idx, veh, ped, rule, "ped_conflict",
                    lambda va, vb: np.linalg.norm(va) >= rule.min_vehicle_speed_mps,
                )
                if ev:
                    out.append(ev)
        return out

    # ------------------------------------------------------------------ violations
    def _wrong_way(self, t, frame_idx, tracks) -> list[Event]:
        rule = self.cfg.rules.wrong_way
        out = []
        for tr in tracks:
            if not tr.is_vehicle or ("wrong_way", tr.track_id) in self._fired:
                continue
            if t - self._ww_last_eval.get(tr.track_id, -1e9) < rule.window_s / 3:
                continue
            foot = (tr.last.px, tr.last.py)
            lane = next((l for l in self.cfg.lanes if point_in_poly(foot, self.lane_px[l.id])), None)
            if lane is None:
                continue
            self._ww_last_eval[tr.track_id] = t
            obs = tr.window(rule.window_s)
            if len(obs) < 4 or float(np.linalg.norm(obs[-1].g - obs[0].g)) < rule.min_displacement_m:
                continue
            disp = np.array([obs[-1].px - obs[0].px, obs[-1].py - obs[0].py])
            cos = float(unit(disp) @ unit(lane.direction))
            if cos < rule.cos_threshold:
                self._ww_hits[tr.track_id] = self._ww_hits.get(tr.track_id, 0) + 1
            elif cos > 0:
                self._ww_hits[tr.track_id] = 0
            if self._ww_hits.get(tr.track_id, 0) >= rule.confirm_windows and self._once(("wrong_way", tr.track_id)):
                zone = self.cfg.zone(lane.zone_id)
                out.append(Event(
                    type="wrong_way",
                    severity="high",
                    t=t,
                    frame=frame_idx,
                    track_ids=[tr.track_id],
                    classes=[tr.cls],
                    zone_id=zone.id if zone else lane.id,
                    zone_name=zone.name if zone else lane.name,
                    confidence=round(tr.last.conf, 3),
                    metrics={"lane": lane.id, "direction_cos": round(cos, 2), "speed_mps": round(tr.speed(), 2)},
                    description=f"{tr.cls.title()} #{tr.track_id} moving against the configured direction of {lane.name}",
                ))
        return out

    def _red_light(self, t, frame_idx, tracks) -> list[Event]:
        out = []
        for tr in tracks:
            if not tr.is_vehicle or tr.track_id not in self._prev_foot:
                continue
            prev = self._prev_foot[tr.track_id]
            cur = (tr.last.px, tr.last.py)
            for sl in self.cfg.stop_lines:
                a, b = self.geom.to_px(sl.line[0]), self.geom.to_px(sl.line[1])
                if not segments_intersect(prev, cur, a, b):
                    continue
                motion = np.array([cur[0] - prev[0], cur[1] - prev[1]])
                if float(unit(motion) @ unit(sl.crossing_direction)) <= 0.2:
                    continue
                state = self.signal_state.get(sl.signal_id, "unknown")
                if state != RED or not self._once(("red_light", tr.track_id)):
                    continue
                zone = self.cfg.zone(sl.zone_id)
                out.append(Event(
                    type="red_light",
                    severity="high" if tr.speed() > 8 else "medium",
                    t=t,
                    frame=frame_idx,
                    track_ids=[tr.track_id],
                    classes=[tr.cls],
                    zone_id=zone.id if zone else sl.id,
                    zone_name=zone.name if zone else sl.name,
                    confidence=round(tr.last.conf, 3),
                    metrics={"stop_line": sl.id, "signal": sl.signal_id, "speed_mps": round(tr.speed(), 2)},
                    description=f"{tr.cls.title()} #{tr.track_id} crossed {sl.name} while the signal was red",
                ))
        return out

    def _illegal_stop(self, t, frame_idx, tracks) -> list[Event]:
        rule = self.cfg.rules.illegal_stop
        no_stop = {z.id for z in self.cfg.zones if z.type == "no_stopping"}
        if not no_stop:
            return []
        out = []
        for tr in tracks:
            if not tr.is_vehicle:
                continue
            zones = self.track_zones.get(tr.track_id, set()) & no_stop
            if not zones or len(tr.history) < 5 or tr.speed(1.0) > rule.speed_threshold_mps:
                self._stationary_since.pop(tr.track_id, None)
                continue
            since = self._stationary_since.setdefault(tr.track_id, t)
            if t - since >= rule.dwell_s and self._once(("illegal_stop", tr.track_id)):
                zone = self.cfg.zone(next(iter(zones)))
                out.append(Event(
                    type="illegal_stop",
                    severity="medium" if t - since < 3 * rule.dwell_s else "high",
                    t=t,
                    frame=frame_idx,
                    track_ids=[tr.track_id],
                    classes=[tr.cls],
                    zone_id=zone.id,
                    zone_name=zone.name,
                    confidence=round(tr.last.conf, 3),
                    metrics={"dwell_s": round(t - since, 1)},
                    description=f"{tr.cls.title()} #{tr.track_id} stationary in {zone.name} for {t - since:.0f}s",
                ))
        return out

    def _update_zone_live(self, tracks) -> None:
        for z in self.cfg.zones:
            inside = [tr for tr in tracks if z.id in self.track_zones.get(tr.track_id, set())]
            veh = [tr for tr in inside if tr.is_vehicle and len(tr.history) >= 5]
            speeds = [tr.speed() for tr in veh]
            self.zone_live[z.id] = {
                "vehicles": sum(1 for tr in inside if tr.is_vehicle),
                "people": sum(1 for tr in inside if tr.is_person),
                "avg_speed_mps": round(float(np.mean(speeds)), 2) if speeds else None,
            }

    def _congestion(self, t, frame_idx) -> list[Event]:
        rule = self.cfg.rules.congestion
        out = []
        for z in self.cfg.zones:
            if z.type not in ("road", "intersection"):
                continue
            live = self.zone_live.get(z.id, {})
            spd = live.get("avg_speed_mps")
            congested = live.get("vehicles", 0) >= rule.min_vehicles and spd is not None and spd <= rule.max_avg_speed_mps
            if not congested:
                self._congested_since.pop(z.id, None)
                continue
            since = self._congested_since.setdefault(z.id, t)
            if t - since >= rule.sustain_s and t - self._congestion_last.get(z.id, -1e9) >= rule.cooldown_s:
                self._congestion_last[z.id] = t
                out.append(Event(
                    type="congestion",
                    severity="medium",
                    t=t,
                    frame=frame_idx,
                    track_ids=[],
                    classes=[],
                    zone_id=z.id,
                    zone_name=z.name,
                    confidence=1.0,
                    metrics={"vehicles": live["vehicles"], "avg_speed_mps": spd, "duration_s": round(t - since, 1)},
                    description=f"{live['vehicles']} vehicles averaging {spd:.1f} m/s in {z.name} for {t - since:.0f}s",
                ))
        return out

    # ------------------------------------------------------------------ counting
    def _count_lines(self, tracks) -> None:
        for cl in self.cfg.counting_lines:
            a, b = self.geom.to_px(cl.line[0]), self.geom.to_px(cl.line[1])
            tally = self.line_counts.setdefault(cl.id, {})
            for tr in tracks:
                prev = self._prev_foot.get(tr.track_id)
                if prev is None:
                    continue
                cur = (tr.last.px, tr.last.py)
                if segments_intersect(prev, cur, a, b) and self._once(("count", cl.id, tr.track_id)):
                    d = "fwd" if side_of_line(cur, a, b) > 0 else "back"
                    c = tally.setdefault(tr.cls, {"fwd": 0, "back": 0})
                    c[d] += 1


def _overlap_ratio(inner, outer) -> float:
    """Fraction of `inner` box area covered by `outer`."""
    x1, y1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    x2, y2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(1e-6, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return inter / area
