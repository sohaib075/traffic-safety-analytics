"""Traffic-signal state estimation."""
from __future__ import annotations

from collections import Counter, deque

import cv2
import numpy as np

from ..camera_config import Signal

RED, GREEN, AMBER, UNKNOWN = "red", "green", "amber", "unknown"


class SignalMonitor:
    def __init__(self, sig: Signal, width: int, height: int):
        self.sig = sig
        self.w, self.h = width, height
        self.readings: deque[str] = deque(maxlen=5)
        self.state = UNKNOWN

    def update(self, t: float, frame: np.ndarray) -> str:
        mode = self.sig.mode
        if mode == "always_red":
            self.state = RED
        elif mode == "always_green":
            self.state = GREEN
        elif mode == "schedule":
            phase = (t + self.sig.offset_s) % self.sig.cycle_s
            self.state = RED if phase < self.sig.red_s else GREEN
        elif mode == "roi" and self.sig.roi:
            self.readings.append(self._classify(frame))
            known = [r for r in self.readings if r != UNKNOWN]
            if known:
                self.state = Counter(known).most_common(1)[0][0]
        return self.state

    def _classify(self, frame: np.ndarray) -> str:
        x1, y1, x2, y2 = self.sig.roi
        crop = frame[int(y1 * self.h):int(y2 * self.h), int(x1 * self.w):int(x2 * self.w)]
        if crop.size == 0:
            return UNKNOWN
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        bright = (hsv[..., 1] > 90) & (hsv[..., 2] > 130)
        hue = hsv[..., 0]
        counts = {
            RED: int(np.count_nonzero(bright & ((hue < 10) | (hue > 165)))),
            AMBER: int(np.count_nonzero(bright & (hue >= 12) & (hue <= 32))),
            GREEN: int(np.count_nonzero(bright & (hue >= 45) & (hue <= 95))),
        }
        best = max(counts, key=counts.get)
        return best if counts[best] >= max(4, 0.01 * hue.size) else UNKNOWN
