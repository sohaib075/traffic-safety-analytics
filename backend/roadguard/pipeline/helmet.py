"""Helmet compliance for motorcycle riders.

COCO-pretrained YOLO has no helmet class, so this needs a custom model (see backend/training).
Two model types are supported, picked from the model's task:

* ``classify`` (recommended, trained by training/train_helmet_colab.ipynb on the HELMET dataset):
  classifies a crop of the tracked motorcycle plus its overlapping riders as
  ``helmet`` (all riders helmeted) or ``no_helmet`` (at least one rider without).
* ``detect``: a helmet / no_helmet head detector run on each rider's head region.

Each check is a vote on the motorcycle track; an event fires once enough ``no_helmet`` votes
outweigh ``helmet`` votes. When no model is configured the check is disabled.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..camera_config import HelmetRule
from .rules import Event, _overlap_ratio
from .tracks import Track


def letterbox_square(img: np.ndarray, fill: int = 114) -> np.ndarray:
    """Pad to a centred square. Must match training/prepare_helmet_crops.py: YOLO-cls resizes the
    short side and centre-crops, which would cut the riders' heads off a tall crop."""
    import cv2

    h, w = img.shape[:2]
    s = max(h, w)
    top, left = (s - h) // 2, (s - w) // 2
    return cv2.copyMakeBorder(img, top, s - h - top, left, s - w - left, cv2.BORDER_CONSTANT, value=(fill, fill, fill))


def riders_of(moto: Track, people: list[Track], max_riders: int = 3) -> list[Track]:
    """People actually sitting on this motorcycle, not just overlapping it in dense traffic.

    A rider's box overlaps the bike, is horizontally centred over it, and their feet (box bottom)
    are below the top of the bike. At most ``max_riders`` best-overlapping people are kept.
    """
    mx1, my1, mx2, my2 = moto.last.bbox
    cands = []
    for p in people:
        px1, py1, px2, py2 = p.last.bbox
        ov = _overlap_ratio(p.last.bbox, moto.last.bbox)
        cx = (px1 + px2) / 2
        if ov > 0.3 and mx1 <= cx <= mx2 and py2 >= my1 + 0.25 * (my2 - my1):
            cands.append((ov, p))
    cands.sort(key=lambda c: -c[0])
    return [p for _, p in cands[:max_riders]]


def motorcycle_crop_box(moto: Track, riders: list[Track], w: int, h: int, pad: float = 0.08):
    """Union of the motorcycle and rider boxes, padded like the training crops."""
    boxes = [moto.last.bbox] + [r.last.bbox for r in riders]
    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    return (int(max(0, x1 - px)), int(max(0, y1 - 1.5 * py)), int(min(w, x2 + px)), int(min(h, y2 + py)))


class HelmetChecker:
    def __init__(self, rule: HelmetRule, device: str):
        self.rule = rule
        self.model = None
        self.device = device
        if rule.enabled and rule.model:
            from pathlib import Path

            from ultralytics import YOLO

            from .. import settings

            path = Path(rule.model)
            path = path if path.is_absolute() else settings.BACKEND_DIR / path
            if not path.exists():
                import logging

                logging.getLogger(__name__).warning("helmet model %s not found; helmet check disabled", path)
                self._fired: set[int] = set()
                self._last_check: dict[int, float] = {}
                return
            self.model = YOLO(str(path))
            names = {i: n.lower() for i, n in self.model.names.items()}
            self.no_ids = {i for i, n in names.items() if n in [c.lower() for c in rule.no_helmet_classes]}
            self.yes_ids = {i for i, n in names.items() if n in [c.lower() for c in rule.helmet_classes]}
        self._fired: set[int] = set()
        self._last_check: dict[int, float] = {}

    @property
    def active(self) -> bool:
        return self.model is not None

    @property
    def is_classifier(self) -> bool:
        return self.model is not None and self.model.task == "classify"

    def process(self, t: float, frame_idx: int, frame: np.ndarray, tracks: list[Track]) -> list[Event]:
        if not self.active:
            return []
        out = []
        motos = [tr for tr in tracks if tr.cls == "motorcycle"]
        people = [tr for tr in tracks if tr.is_person]
        h, w = frame.shape[:2]
        for moto in motos:
            if t - self._last_check.get(moto.track_id, -1e9) < self.rule.check_every_s - 1e-6:  # float frame times
                continue
            self._last_check[moto.track_id] = t
            riders = riders_of(moto, people)
            if self.is_classifier:
                x1, y1, x2, y2 = motorcycle_crop_box(moto, riders, w, h)
                bx1, _, bx2, _ = moto.last.bbox
                at_edge = bx1 <= 2 or bx2 >= w - 2  # entering/leaving: only part of the bike is visible
                if y2 - y1 >= self.rule.min_crop_height and not (self.rule.skip_edge_crops and at_edge):
                    p = self._no_helmet_prob(frame[y1:y2, x1:x2])
                    if p is not None:
                        moto.helmet_probs.append(p)
                ev = self._decide_by_mean(t, frame_idx, moto, riders)
            else:
                for rider in riders:
                    vote = self._detect_head(frame, rider.last.bbox)
                    if vote:
                        moto.helmet_votes[vote] += 1
                ev = self._decide_by_votes(t, frame_idx, moto, riders)
            if ev:
                out.append(ev)
        return out

    def _event(self, t, frame_idx, moto, riders, confidence, metrics, description) -> Event:
        self._fired.add(moto.track_id)
        return Event(
            type="helmet_violation",
            severity="medium",
            t=t,
            frame=frame_idx,
            track_ids=[moto.track_id, *[r.track_id for r in riders]],
            classes=["motorcycle", *["person"] * len(riders)],
            confidence=confidence,
            metrics=metrics,
            description=description,
        )

    def _decide_by_mean(self, t, frame_idx, moto: Track, riders) -> Optional[Event]:
        """Classifier mode: average P(no_helmet) over the track's checks (as evaluated offline)."""
        probs = moto.helmet_probs
        if len(probs) < self.rule.min_checks:
            return None
        mean = float(np.mean(probs))
        moto.helmet_label = "no_helmet" if mean >= self.rule.threshold else "helmet"
        # Sequential decision: an early incident needs a more confident mean; borderline tracks
        # wait until confirm_checks so an early fluke doesn't raise an incident the track later disowns.
        need = self.rule.threshold if len(probs) >= self.rule.confirm_checks else max(self.rule.threshold, self.rule.early_threshold)
        if mean < need or moto.track_id in self._fired:
            return None
        return self._event(
            t, frame_idx, moto, riders, round(mean, 2),
            {"mean_p_no_helmet": round(mean, 3), "checks": len(probs), "threshold": self.rule.threshold},
            f"Rider(s) on motorcycle #{moto.track_id} classified without helmet "
            f"(mean P={mean:.2f} over {len(probs)} checks)",
        )

    def _decide_by_votes(self, t, frame_idx, moto: Track, riders) -> Optional[Event]:
        """Head-detector mode: count per-check votes."""
        no, yes = moto.helmet_votes["no_helmet"], moto.helmet_votes["helmet"]
        if no + yes:
            moto.helmet_label = "no_helmet" if no > yes else "helmet"
        if no < self.rule.min_votes or no <= yes or moto.track_id in self._fired:
            return None
        return self._event(
            t, frame_idx, moto, riders, round(no / max(1, no + yes), 2),
            {"no_helmet_votes": no, "helmet_votes": yes},
            f"Rider(s) on motorcycle #{moto.track_id} classified without helmet in {no} of {no + yes} checks",
        )

    def _no_helmet_prob(self, crop: np.ndarray) -> Optional[float]:
        if crop.size == 0:
            return None
        crop = letterbox_square(crop)  # same as training; YOLO-cls centre-crops otherwise
        probs = self.model.predict(crop, imgsz=self.rule.imgsz, verbose=False, device=self.device)[0].probs
        return float(sum(float(probs.data[i]) for i in self.no_ids))

    def _detect_head(self, frame: np.ndarray, bbox) -> Optional[str]:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        bh = y2 - y1
        # head region: top ~40% of the rider box, slightly widened
        cx1, cx2 = int(max(0, x1 - 0.1 * (x2 - x1))), int(min(w, x2 + 0.1 * (x2 - x1)))
        cy1, cy2 = int(max(0, y1 - 0.1 * bh)), int(min(h, y1 + 0.4 * bh))
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < 12 or crop.shape[1] < 12:
            return None
        res = self.model.predict(crop, imgsz=160, conf=0.35, verbose=False, device=self.device)[0]
        if res.boxes is None or len(res.boxes) == 0:
            return None
        cls = int(res.boxes.cls[int(res.boxes.conf.argmax())])
        if cls in self.no_ids:
            return "no_helmet"
        if cls in self.yes_ids:
            return "helmet"
        return None
