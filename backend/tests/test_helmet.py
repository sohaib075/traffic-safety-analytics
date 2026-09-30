"""HelmetChecker (classifier mode) with a stub model — no weights needed."""
from types import SimpleNamespace

import numpy as np

from roadguard.camera_config import HelmetRule
from roadguard.pipeline.helmet import HelmetChecker, letterbox_square, motorcycle_crop_box
from roadguard.pipeline.tracks import Observation, Track


class StubClassifier:
    task = "classify"
    names = {0: "helmet", 1: "no_helmet"}

    def __init__(self, p_no):
        self.p_no, self.calls = p_no, []

    def predict(self, crop, imgsz, verbose, device):
        self.calls.append(crop.shape)
        p = self.p_no(len(self.calls)) if callable(self.p_no) else self.p_no
        return [SimpleNamespace(probs=SimpleNamespace(data=[1 - p, p]))]


def track(tid, cls, box):
    tr = Track(track_id=tid)
    tr.cls_votes[cls] += 1
    tr.history.append(Observation(0.0, 0, (box[0] + box[2]) / 2, box[3], np.zeros(2), box, 0.9))
    return tr


def checker(p_no, **rule):
    c = HelmetChecker(HelmetRule(enabled=False), "cpu")  # no model load
    c.rule = HelmetRule(enabled=True, model="stub", **rule)
    c.model = StubClassifier(p_no)
    c.no_ids, c.yes_ids = {1}, {0}
    return c


def run(c, frames=20, fps=10):
    frame = np.zeros((720, 1280, 3), np.uint8)
    moto = track(1, "motorcycle", (500, 400, 580, 520))
    rider = track(2, "person", (505, 330, 575, 480))
    events = []
    for i in range(frames):
        events += c.process(i / fps, i, frame, [moto, rider])
    return events, moto


def test_violation_fires_once_on_mean_probability():
    ev, moto = run(checker(0.7))
    assert len(ev) == 1 and ev[0].type == "helmet_violation"
    assert ev[0].track_ids == [1, 2]
    assert ev[0].metrics["checks"] == 4  # fires as soon as min_checks is reached
    assert moto.helmet_label == "no_helmet"
    assert len(moto.helmet_probs) == 10  # every 0.2 s over 2 s


def test_compliant_rider_no_event():
    ev, moto = run(checker(0.2))
    assert not ev and moto.helmet_label == "helmet"


def test_uncertain_checks_still_count_but_wait_for_confirmation():
    # Old behaviour abstained below 0.6 confidence, which silently dropped most no-helmet
    # evidence; a steady 0.55 must now be flagged — but only once confirm_checks is reached.
    ev, _ = run(checker(0.55))
    assert len(ev) == 1 and ev[0].metrics["checks"] == 8


def test_early_fluke_does_not_raise_incident():
    # First checks look like no helmet, the rest clearly show a helmet.
    ev, moto = run(checker(lambda n: 0.58 if n <= 5 else 0.1))
    assert not ev and moto.helmet_label == "helmet"


def test_threshold_is_configurable():
    ev, _ = run(checker(0.55, threshold=0.7))
    assert not ev


def test_needs_min_checks():
    ev, moto = run(checker(0.9, min_checks=4), frames=6)  # checks at t=0,0.2,0.4 only
    assert not ev and moto.helmet_label is None


def test_motorcycle_cut_off_at_frame_edge_is_not_judged():
    c = checker(0.9)
    frame = np.zeros((720, 1280, 3), np.uint8)
    moto = track(1, "motorcycle", (0, 400, 80, 520))  # touching the left border
    for i in range(20):
        assert not c.process(i / 10, i, frame, [moto])
    assert not moto.helmet_probs and not c.model.calls


def test_riders_are_people_on_the_bike_not_bystanders():
    from roadguard.pipeline.helmet import riders_of

    moto = track(1, "motorcycle", (500, 400, 600, 520))
    driver = track(2, "person", (510, 330, 590, 480))
    pillion = track(3, "person", (530, 335, 610, 485))
    beside = track(4, "person", (560, 300, 700, 520))  # overlaps, but centred off the bike
    behind = track(5, "person", (505, 250, 595, 405))  # overlaps, but feet above the bike
    assert {r.track_id for r in riders_of(moto, [driver, pillion, beside, behind])} == {2, 3}


def test_crop_includes_rider_head_and_is_square_after_letterbox():
    moto = track(1, "motorcycle", (500, 400, 580, 520))
    rider = track(2, "person", (505, 330, 575, 480))
    x1, y1, x2, y2 = motorcycle_crop_box(moto, [rider], 1280, 720)
    assert y1 < 330 and y2 > 520 and x1 < 500 and x2 > 580
    sq = letterbox_square(np.zeros((y2 - y1, x2 - x1, 3), np.uint8))
    assert sq.shape[0] == sq.shape[1] == max(y2 - y1, x2 - x1)
