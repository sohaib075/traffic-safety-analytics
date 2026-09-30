"""Frame rendering: privacy blur, scene overlays, boxes, trails and event highlights."""
from __future__ import annotations

import cv2
import numpy as np

from ..camera_config import CameraConfig
from .geometry import SceneGeometry
from .rules import EVENT_LABELS, RuleEngine
from .tracks import Track

CLASS_COLORS = {  # BGR
    "car": (235, 170, 60),
    "motorcycle": (60, 200, 240),
    "bus": (200, 120, 230),
    "truck": (120, 140, 240),
    "bicycle": (160, 220, 120),
    "person": (90, 230, 90),
}
SIGNAL_COLORS = {"red": (40, 40, 230), "green": (60, 200, 60), "amber": (0, 170, 250), "unknown": (160, 160, 160)}
ALERT = (40, 40, 240)


def blur_heads(frame: np.ndarray, tracks: list[Track]) -> None:
    """Blur the upper part of each person box in place (face privacy without a face model)."""
    h, w = frame.shape[:2]
    for tr in tracks:
        if not tr.is_person:
            continue
        x1, y1, x2, y2 = (int(v) for v in tr.last.bbox)
        hh = max(4, int((y2 - y1) * 0.28))
        x1, x2, y1 = max(0, x1), min(w, x2), max(0, y1)
        y2 = min(h, y1 + hh)
        roi = frame[y1:y2, x1:x2]
        if roi.size:
            k = max(3, (min(roi.shape[:2]) // 2) | 1)
            frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)


def blur_boxes(frame: np.ndarray, boxes) -> None:
    h, w = frame.shape[:2]
    for x1, y1, x2, y2 in boxes:
        x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
        roi = frame[y1:y2, x1:x2]
        if roi.size:
            k = max(3, (min(roi.shape[:2]) // 2) | 1)
            frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)


def _label(img, text, org, color, scale=0.45):
    (tw, th), bl = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = int(org[0]), int(org[1])
    cv2.rectangle(img, (x, y - th - bl - 2), (x + tw + 4, y + 1), color, -1)
    cv2.putText(img, text, (x + 2, y - bl), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


class Annotator:
    def __init__(self, cfg: CameraConfig, geom: SceneGeometry, engine: RuleEngine):
        self.cfg, self.geom, self.engine = cfg, geom, engine
        self.highlights: dict[int, tuple[float, str]] = {}  # track_id -> (until_t, label)
        self.banners: list[tuple[float, str]] = []

    def flag(self, t: float, track_ids: list[int], label: str, hold_s: float = 3.0) -> None:
        for tid in track_ids:
            self.highlights[tid] = (t + hold_s, label)
        self.banners.append((t + hold_s, label))

    def draw(self, frame: np.ndarray, t: float, tracks: list[Track], counts: dict[str, int]) -> np.ndarray:
        img = frame
        overlay = img.copy()
        for z in self.cfg.zones:
            poly = self.geom.poly_px(z.polygon).astype(np.int32)
            color = {"crosswalk": (230, 230, 230), "no_stopping": (60, 60, 220), "intersection": (0, 190, 255)}.get(z.type, (200, 160, 60))
            cv2.fillPoly(overlay, [poly], color)
        cv2.addWeighted(overlay, 0.12, img, 0.88, 0, img)
        for z in self.cfg.zones:
            poly = self.geom.poly_px(z.polygon).astype(np.int32)
            cv2.polylines(img, [poly], True, (220, 220, 220), 1, cv2.LINE_AA)
            _label(img, z.name, poly.min(axis=0) + [0, 14], (70, 70, 70), 0.4)
        for lane in self.cfg.lanes:
            poly = self.geom.poly_px(lane.polygon)
            c = poly.mean(axis=0)
            d = np.array(lane.direction, dtype=float)
            d = d / (np.linalg.norm(d) + 1e-9) * min(self.geom.width, self.geom.height) * 0.06
            cv2.arrowedLine(img, tuple((c - d).astype(int)), tuple((c + d).astype(int)), (255, 255, 255), 2, cv2.LINE_AA, tipLength=0.35)
        for sl in self.cfg.stop_lines:
            state = self.engine.signal_state.get(sl.signal_id, "unknown")
            a, b = self.geom.to_px(sl.line[0]), self.geom.to_px(sl.line[1])
            cv2.line(img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), SIGNAL_COLORS[state], 3, cv2.LINE_AA)
        for cl in self.cfg.counting_lines:
            a, b = self.geom.to_px(cl.line[0]), self.geom.to_px(cl.line[1])
            cv2.line(img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (255, 200, 0), 1, cv2.LINE_AA)

        self.highlights = {k: v for k, v in self.highlights.items() if v[0] >= t}
        for tr in tracks:
            x1, y1, x2, y2 = (int(v) for v in tr.last.bbox)
            hl = self.highlights.get(tr.track_id)
            color = ALERT if hl else CLASS_COLORS.get(tr.cls, (200, 200, 200))
            pts = np.array([(o.px, o.py) for o in list(tr.history)[-40:]], dtype=np.int32)
            if len(pts) > 1:
                cv2.polylines(img, [pts], False, color, 2 if hl else 1, cv2.LINE_AA)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 3 if hl else 2)
            _label(img, f"{tr.cls} #{tr.track_id}", (x1, y1), color)
            if hl:
                _label(img, hl[1], (x1, y2 + 16), ALERT)

        # HUD
        self.banners = [b for b in self.banners if b[0] >= t]
        hud = f"RoadGuard AI  t={t:6.1f}s  " + "  ".join(f"{k}:{v}" for k, v in counts.items() if v)
        cv2.rectangle(img, (0, 0), (img.shape[1], 24), (20, 20, 20), -1)
        cv2.putText(img, hud, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1, cv2.LINE_AA)
        for i, (_, text) in enumerate(self.banners[-3:]):
            _label(img, f"! {text}", (8, 50 + 26 * i), ALERT, 0.6)
        return img


def draw_event_snapshot(img: np.ndarray, tracks_by_id: dict[int, Track], track_ids: list[int], etype: str) -> np.ndarray:
    """Extra emphasis on the evidence still: connector line between involved objects."""
    pts = []
    for tid in track_ids:
        tr = tracks_by_id.get(tid)
        if tr is None:
            continue
        x1, y1, x2, y2 = (int(v) for v in tr.last.bbox)
        cv2.rectangle(img, (x1 - 3, y1 - 3), (x2 + 3, y2 + 3), (255, 255, 255), 1)
        pts.append((int((x1 + x2) / 2), int((y1 + y2) / 2)))
    if len(pts) == 2:
        cv2.line(img, pts[0], pts[1], ALERT, 2, cv2.LINE_AA)
        mid = ((pts[0][0] + pts[1][0]) // 2, (pts[0][1] + pts[1][1]) // 2)
        cv2.circle(img, mid, 10, ALERT, 2, cv2.LINE_AA)
    _label(img, EVENT_LABELS.get(etype, etype).upper(), (8, img.shape[0] - 10), ALERT, 0.7)
    return img
