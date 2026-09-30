"""Rule-engine tests driven by synthetic trajectories (no video / model needed).

Scene: 1000×1000 px frame, uncalibrated at 100 m across → 0.1 m per pixel, 10 fps.
"""
import numpy as np
import pytest

from roadguard.camera_config import CameraConfig
from roadguard.pipeline.geometry import SceneGeometry
from roadguard.pipeline.rules import RuleEngine
from roadguard.pipeline.tracks import TrackManager

W = H = 1000
FPS = 10.0
BOX = {"car": (40, 20), "person": (8, 18), "motorcycle": (12, 18), "bus": (100, 30)}


def cfg(**kw) -> CameraConfig:
    base = {"id": "t", "name": "test", "calibration": {"approx_scene_width_m": 100}}
    base.update(kw)
    return CameraConfig.model_validate(base)


def simulate(c: CameraConfig, actors: dict, seconds: float):
    """actors: {tid: (cls, fn(t) -> (px, py) or None)}; returns all events."""
    geom = SceneGeometry(c.calibration, W, H)
    tm = TrackManager(geom)
    eng = RuleEngine(c, geom)
    frame = np.zeros((H, W, 3), np.uint8)
    events = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        dets = []
        for tid, (cls, fn) in actors.items():
            p = fn(t)
            if p is None:
                continue
            bw, bh = BOX.get(cls, (30, 20))
            dets.append((tid, cls, 0.9, (p[0] - bw / 2, p[1] - bh, p[0] + bw / 2, p[1])))
        tm.update(t, i, dets)
        events += eng.process(t, i, frame, tm.active())
    return events, eng


def lin(x0, y0, vx, vy, t0=0.0):
    """Straight line in px with velocity in m/s (0.1 m/px → ×10 px/m)."""
    return lambda t: (x0 + vx * 10 * (t - t0), y0 + vy * 10 * (t - t0)) if t >= t0 else None


# ---------------------------------------------------------------- near-miss
def test_near_miss_crossing_paths():
    # Two cars heading for the same point (500,500) at 10 m/s from 30 m away, perpendicular.
    ev, _ = simulate(cfg(), {1: ("car", lin(200, 500, 10, 0)), 2: ("car", lin(500, 200, 0, 10))}, 3.0)
    nm = [e for e in ev if e.type == "near_miss"]
    assert len(nm) == 1
    assert set(nm[0].track_ids) == {1, 2}
    assert nm[0].metrics["ttc_s"] <= 1.5


def test_no_near_miss_parallel_traffic():
    ev, _ = simulate(cfg(), {1: ("car", lin(100, 500, 12, 0)), 2: ("car", lin(100, 560, 12, 0))}, 4.0)
    assert not [e for e in ev if e.type == "near_miss"]


def test_no_near_miss_stationary_queue():
    ev, _ = simulate(cfg(), {1: ("car", lambda t: (500, 500)), 2: ("car", lambda t: (545, 500))}, 4.0)
    assert not ev


def test_no_near_miss_diverging():
    ev, _ = simulate(cfg(), {1: ("car", lin(500, 500, -10, 0)), 2: ("car", lin(560, 500, 10, 0))}, 3.0)
    assert not [e for e in ev if e.type == "near_miss"]


def test_near_miss_rear_end_closing():
    # Follower at 15 m/s closes on a leader at 3 m/s.
    ev, _ = simulate(cfg(), {1: ("car", lin(100, 500, 15, 0)), 2: ("car", lin(400, 500, 3, 0))}, 3.0)
    assert [e for e in ev if e.type == "near_miss"]


def test_near_miss_zone_restriction():
    c = cfg(zones=[{"id": "z", "name": "Z", "type": "intersection", "polygon": [[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1]]}],
            rules={"near_miss": {"zones": ["z"]}})
    ev, _ = simulate(c, {1: ("car", lin(200, 500, 10, 0)), 2: ("car", lin(500, 200, 0, 10))}, 3.0)
    assert not [e for e in ev if e.type == "near_miss"]


# ---------------------------------------------------------------- pedestrian conflict
def test_pedestrian_conflict():
    ev, _ = simulate(cfg(), {1: ("car", lin(200, 500, 10, 0)), 2: ("person", lin(500, 480, 0, 0.5))}, 3.5)
    pc = [e for e in ev if e.type == "ped_conflict"]
    assert len(pc) == 1 and pc[0].classes == ["car", "person"]


def test_rider_is_not_a_pedestrian():
    ride = lin(200, 500, 8, 0)
    ev, _ = simulate(cfg(), {1: ("motorcycle", ride), 2: ("person", lambda t: (ride(t)[0], ride(t)[1] - 6)),
                             3: ("car", lin(700, 500, -8, 0))}, 3.0)
    assert not [e for e in ev if e.type == "ped_conflict" and 2 in e.track_ids]


# ---------------------------------------------------------------- wrong way
LANE = {"id": "l1", "name": "Lane 1", "polygon": [[0, 0.4], [1, 0.4], [1, 0.6], [0, 0.6]], "direction": [1, 0]}


def test_wrong_way_detected():
    ev, _ = simulate(cfg(lanes=[LANE]), {1: ("car", lin(900, 500, -10, 0))}, 5.0)
    ww = [e for e in ev if e.type == "wrong_way"]
    assert len(ww) == 1 and ww[0].track_ids == [1]


def test_right_way_not_flagged():
    ev, _ = simulate(cfg(lanes=[LANE]), {1: ("car", lin(100, 500, 10, 0))}, 5.0)
    assert not [e for e in ev if e.type == "wrong_way"]


def test_wrong_way_ignores_pedestrians():
    ev, _ = simulate(cfg(lanes=[LANE]), {1: ("person", lin(900, 500, -3, 0))}, 8.0)
    assert not [e for e in ev if e.type == "wrong_way"]


# ---------------------------------------------------------------- red light
def red_cfg(mode):
    return cfg(signals=[{"id": "s", "mode": mode}],
               stop_lines=[{"id": "sl", "line": [[0.5, 0.3], [0.5, 0.7]], "crossing_direction": [1, 0], "signal_id": "s"}])


def test_red_light_violation():
    ev, _ = simulate(red_cfg("always_red"), {1: ("car", lin(300, 500, 10, 0))}, 4.0)
    rl = [e for e in ev if e.type == "red_light"]
    assert len(rl) == 1


def test_green_light_ok():
    ev, _ = simulate(red_cfg("always_green"), {1: ("car", lin(300, 500, 10, 0))}, 4.0)
    assert not [e for e in ev if e.type == "red_light"]


def test_red_light_opposite_direction_ignored():
    ev, _ = simulate(red_cfg("always_red"), {1: ("car", lin(700, 500, -10, 0))}, 4.0)
    assert not [e for e in ev if e.type == "red_light"]


def test_schedule_signal():
    c = cfg(signals=[{"id": "s", "mode": "schedule", "cycle_s": 10, "red_s": 5}],
            stop_lines=[{"id": "sl", "line": [[0.5, 0], [0.5, 1]], "crossing_direction": [1, 0], "signal_id": "s"}])
    # crosses x=500 at t=2s (red) and a second car at t=7s (green)
    ev, _ = simulate(c, {1: ("car", lin(300, 400, 10, 0)), 2: ("car", lin(300, 600, 10, 0, t0=5.0))}, 9.0)
    assert [e.track_ids for e in ev if e.type == "red_light"] == [[1]]


# ---------------------------------------------------------------- illegal stop / congestion
def test_illegal_stop():
    c = cfg(zones=[{"id": "ns", "name": "No stopping", "type": "no_stopping", "polygon": [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]}],
            rules={"illegal_stop": {"dwell_s": 5}})
    ev, _ = simulate(c, {1: ("car", lambda t: (500, 500)), 2: ("car", lambda t: (100, 100))}, 7.0)
    st = [e for e in ev if e.type == "illegal_stop"]
    assert len(st) == 1 and st[0].track_ids == [1]


def test_counting_line():
    c = cfg(counting_lines=[{"id": "c", "line": [[0.5, 0], [0.5, 1]]}])
    _, eng = simulate(c, {1: ("car", lin(300, 300, 10, 0)), 2: ("bus", lin(700, 600, -10, 0)),
                          3: ("car", lin(300, 800, 10, 0))}, 4.0)
    assert eng.line_counts["c"]["car"]["fwd"] + eng.line_counts["c"]["car"]["back"] == 2
    assert sum(eng.line_counts["c"]["bus"].values()) == 1


# ---------------------------------------------------------------- geometry
def test_homography_calibration():
    c = cfg(calibration={"image_points": [[0, 0], [1, 0], [1, 1], [0, 1]], "world_points": [[0, 0], [50, 0], [50, 20], [0, 20]]})
    g = SceneGeometry(c.calibration, W, H)
    assert g.calibrated
    assert np.allclose(g.to_ground(1000, 1000), [50, 20], atol=1e-3)
