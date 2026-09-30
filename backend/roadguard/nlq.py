"""Tiny natural-language → incident filter parser (used by search and the offline analyst)."""
from __future__ import annotations

import re
from typing import Optional

TYPE_KEYWORDS = {
    "near_miss": ["near-miss", "near miss", "nearmiss", "near-misses", "near misses", "conflict between vehicles", "close call"],
    "ped_conflict": ["pedestrian", "ped conflict", "walker", "crossing conflict"],
    "red_light": ["red-light", "red light", "signal violation", "ran the light", "jumped the light"],
    "wrong_way": ["wrong-way", "wrong way", "against traffic", "opposite direction"],
    "illegal_stop": ["illegal stop", "illegal parking", "parking", "stopped", "stopping"],
    "congestion": ["congestion", "traffic jam", "jam", "queue"],
    "helmet_violation": ["helmet"],
}

PERIODS = {
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 24),
    "rush hour": (16, 19),
}

_HOUR = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"


def _to_24(h: str, ampm: Optional[str]) -> int:
    hv = int(h)
    if ampm:
        a = ampm.replace(".", "").lower()
        if a == "pm" and hv < 12:
            hv += 12
        if a == "am" and hv == 12:
            hv = 0
    return hv


def parse(text: str) -> dict:
    t = text.lower()
    types = [k for k, kws in TYPE_KEYWORDS.items() if any(kw in t for kw in kws)]
    if "violation" in t and not types:
        types = ["red_light", "wrong_way", "helmet_violation", "illegal_stop"]
    severities = None
    if re.search(r"\b(serious|severe|major|critical|dangerous|high[- ]severity|high risk)\b", t):
        severities = ["high", "medium"] if "high" not in t else ["high"]
    hour_from = hour_to = None
    m = re.search(rf"(?:between|from)\s+{_HOUR}\s+(?:and|to|-|until)\s+{_HOUR}", t)
    if m:
        ap2 = m.group(6)
        ap1 = m.group(3) or ap2  # "between 5 and 8 pm"
        hour_from, hour_to = _to_24(m.group(1), ap1), _to_24(m.group(4), ap2)
    else:
        m = re.search(rf"(?:after|since)\s+{_HOUR}", t)
        if m:
            hour_from, hour_to = _to_24(m.group(1), m.group(3)), 24
        m2 = re.search(rf"before\s+{_HOUR}", t)
        if m2:
            hour_from, hour_to = hour_from or 0, _to_24(m2.group(1), m2.group(3))
        if hour_from is None:
            for name, (a, b) in PERIODS.items():
                if name in t:
                    hour_from, hour_to = a, b
                    break
    return {"types": types or None, "severities": severities, "hour_from": hour_from, "hour_to": hour_to}
