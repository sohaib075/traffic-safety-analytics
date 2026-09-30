"""Image ↔ ground-plane geometry and small 2D helpers."""
from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from ..camera_config import Calibration, Point


class SceneGeometry:
    """Converts pixel positions to approximate ground-plane metres."""

    def __init__(self, calib: Calibration, width: int, height: int):
        self.width, self.height = width, height
        self.calibrated = calib.has_homography
        if self.calibrated:
            src = np.array([[x * width, y * height] for x, y in calib.image_points], dtype=np.float32)
            dst = np.array(calib.world_points, dtype=np.float32)
            self.H, _ = cv2.findHomography(src, dst)
        else:
            self.H = None
            self.m_per_px = calib.approx_scene_width_m / float(width)

    def to_px(self, p: Point) -> tuple[float, float]:
        return p[0] * self.width, p[1] * self.height

    def poly_px(self, poly: Sequence[Point]) -> np.ndarray:
        return np.array([self.to_px(p) for p in poly], dtype=np.float32)

    def to_ground(self, px: float, py: float) -> np.ndarray:
        if self.H is not None:
            v = self.H @ np.array([px, py, 1.0])
            return v[:2] / v[2]
        return np.array([px * self.m_per_px, py * self.m_per_px])

    def ground_many(self, pts: np.ndarray) -> np.ndarray:
        if len(pts) == 0:
            return pts.reshape(0, 2)
        if self.H is not None:
            return cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float64), self.H).reshape(-1, 2)
        return pts * self.m_per_px


def point_in_poly(pt: tuple[float, float], poly_px: np.ndarray) -> bool:
    return cv2.pointPolygonTest(poly_px, (float(pt[0]), float(pt[1])), False) >= 0


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_intersect(p1, p2, q1, q2) -> bool:
    """True if movement p1→p2 crosses segment q1–q2.

    Half-open on the movement side (a point exactly on the line counts as the far side) so a
    track landing precisely on the line is counted once, not zero or two times.
    """
    d1, d2 = _cross(q1, q2, p1), _cross(q1, q2, p2)
    d3, d4 = _cross(p1, p2, q1), _cross(p1, p2, q2)
    return ((d1 < 0) != (d2 < 0)) and (d3 * d4 <= 0) and (p1[0] != p2[0] or p1[1] != p2[1])


def side_of_line(pt, a, b) -> float:
    """Signed side of point relative to the directed line a→b."""
    return _cross(a, b, pt)


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def closest_approach(p_rel: np.ndarray, v_rel: np.ndarray, horizon: float) -> tuple[float, float]:
    """Closest point of approach for two constant-velocity objects.

    p_rel, v_rel: position/velocity of B relative to A.
    Returns (t_cpa clipped to [0, horizon], distance at t_cpa).
    """
    vv = float(v_rel @ v_rel)
    if vv < 1e-9:
        return 0.0, float(np.linalg.norm(p_rel))
    t = -float(p_rel @ v_rel) / vv
    t = min(max(t, 0.0), horizon)
    return t, float(np.linalg.norm(p_rel + v_rel * t))
