"""Query layer shared by the REST API, PDF reports and the AI analyst."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Optional

import yaml
from sqlalchemy import func, select

from . import settings
from .camera_config import list_camera_configs
from .db import Incident, SessionLocal, TrackRecord, TrafficCount, ZoneSample
from .pipeline.rules import EVENT_LABELS

VEHICLE_KEYS = ("car", "motorcycle", "bus", "truck", "bicycle")


@lru_cache(maxsize=1)
def risk_config() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "risk.yaml").read_text(encoding="utf-8"))


class Range:
    def __init__(self, start: Optional[datetime] = None, end: Optional[datetime] = None, camera: Optional[str] = None):
        self.start = start or datetime(1970, 1, 1)
        self.end = end or datetime(2999, 1, 1)
        self.camera = camera

    @classmethod
    def for_day(cls, day: date, camera: Optional[str] = None) -> "Range":
        start = datetime.combine(day, time.min)
        return cls(start, start + timedelta(days=1), camera)

    def f(self, col_time, col_cam):
        conds = [col_time >= self.start, col_time < self.end]
        if self.camera:
            conds.append(col_cam == self.camera)
        return conds


def data_extent() -> dict:
    with SessionLocal() as s:
        lo = s.scalar(select(func.min(TrafficCount.bucket)))
        hi = s.scalar(select(func.max(TrafficCount.bucket)))
        ilo = s.scalar(select(func.min(Incident.occurred_at)))
        ihi = s.scalar(select(func.max(Incident.occurred_at)))
    lows = [d for d in (lo, ilo) if d]
    highs = [d for d in (hi, ihi) if d]
    return {
        "first": min(lows).isoformat() if lows else None,
        "last": max(highs).isoformat() if highs else None,
    }


def risk_score(event_counts: dict[str, dict[str, int]], vehicles: int) -> dict:
    """event_counts: {type: {severity: n}}. Returns score, level and a per-type breakdown."""
    rc = risk_config()
    breakdown = []
    total = 0.0
    for etype, sevs in event_counts.items():
        w = rc["weights"].get(etype, 1)
        pts = sum(w * rc["severity_multiplier"].get(sev, 1.0) * n for sev, n in sevs.items())
        total += pts
        breakdown.append({"type": etype, "label": EVENT_LABELS.get(etype, etype), "count": sum(sevs.values()),
                          "weight": w, "points": round(pts, 1)})
    denom = max(vehicles, rc["min_vehicles"])
    score = total / denom * rc["per_vehicles"]
    level = rc["levels"][0]["name"]
    for lv in rc["levels"]:
        if score >= lv["min"]:
            level = lv["name"]
    breakdown.sort(key=lambda b: -b["points"])
    return {
        "score": round(score, 1),
        "level": level,
        "weighted_points": round(total, 1),
        "vehicles": vehicles,
        "denominator": denom,
        "breakdown": breakdown,
        "method": f"Σ weight × severity multiplier per {rc['per_vehicles']} vehicles (min denominator {rc['min_vehicles']}). "
                  "Configurable indicator of observed events, not an accident probability.",
    }


def _event_counts(rows) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for etype, sev, n in rows:
        out[etype][sev] += n
    return {k: dict(v) for k, v in out.items()}


def summary(r: Range) -> dict:
    with SessionLocal() as s:
        vol = dict(s.execute(
            select(TrafficCount.cls, func.sum(TrafficCount.count)).where(*r.f(TrafficCount.bucket, TrafficCount.camera_id))
            .group_by(TrafficCount.cls)).all())
        ev_rows = s.execute(
            select(Incident.type, Incident.severity, func.count()).where(*r.f(Incident.occurred_at, Incident.camera_id))
            .where(Incident.status != "dismissed").group_by(Incident.type, Incident.severity)).all()
        status_rows = dict(s.execute(
            select(Incident.status, func.count()).where(*r.f(Incident.occurred_at, Incident.camera_id))
            .group_by(Incident.status)).all())
        helmet = dict(s.execute(
            select(TrackRecord.helmet, func.count()).where(*r.f(TrackRecord.first_seen, TrackRecord.camera_id))
            .where(TrackRecord.cls == "motorcycle").group_by(TrackRecord.helmet)).all())
    vehicles = int(sum(v for k, v in vol.items() if k in VEHICLE_KEYS))
    events = _event_counts(ev_rows)
    ts = timeseries(r, "hour")
    peak = max(ts["buckets"], key=lambda b: b["vehicles"], default=None)
    zones = zone_stats(r)
    top_zone = max(zones, key=lambda z: z["risk"]["score"], default=None) if zones else None
    return {
        "range": {"start": r.start.isoformat(), "end": r.end.isoformat(), "camera": r.camera},
        "volume": {k: int(v) for k, v in vol.items()},
        "vehicles": vehicles,
        "pedestrians": int(vol.get("pedestrian", 0)),
        "events": {k: sum(v.values()) for k, v in events.items()},
        "events_by_severity": events,
        "total_events": sum(sum(v.values()) for v in events.values()),
        "review_status": status_rows,
        "helmet": {
            "motorcycles": int(vol.get("motorcycle", 0)),
            "checked": sum(n for k, n in helmet.items() if k),
            "compliant": int(helmet.get("helmet", 0)),
            "violations": int(helmet.get("no_helmet", 0)),
        },
        "risk": risk_score(events, vehicles),
        "peak_hour": peak["start"] if peak and peak["vehicles"] else None,
        "top_zone": {"id": top_zone["id"], "name": top_zone["name"], "risk": top_zone["risk"]} if top_zone and top_zone["events_total"] else None,
    }


def search_incidents(
    r: Range,
    types: Optional[list[str]] = None,
    severities: Optional[list[str]] = None,
    zone: Optional[str] = None,
    vehicle_class: Optional[str] = None,
    status: Optional[list[str]] = None,
    hour_from: Optional[int] = None,
    hour_to: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    order: str = "desc",
    job: Optional[int] = None,
) -> tuple[int, list[Incident]]:
    with SessionLocal() as s:
        q = s.query(Incident).filter(*r.f(Incident.occurred_at, Incident.camera_id))
        if job is not None:
            q = q.filter(Incident.job_id == job)
        if types:
            q = q.filter(Incident.type.in_(types))
        if severities:
            q = q.filter(Incident.severity.in_(severities))
        if zone:
            q = q.filter(Incident.zone_id == zone)
        if status:
            q = q.filter(Incident.status.in_(status))
        if hour_from is not None or hour_to is not None:
            hf, ht = hour_from or 0, hour_to if hour_to is not None else 24
            hour = func.strftime("%H", Incident.occurred_at)  # zero-padded, so string compare works
            q = q.filter(hour >= f"{hf:02d}", hour < f"{ht:02d}")
        q = q.order_by(Incident.occurred_at.desc() if order == "desc" else Incident.occurred_at.asc())
        rows = q.all()
    if vehicle_class:
        rows = [i for i in rows if vehicle_class in (i.classes or [])]
    return len(rows), rows[offset:offset + limit]


def _bucket(dt: datetime, size: str) -> datetime:
    if size == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    if size == "15min":
        return dt.replace(minute=dt.minute // 15 * 15, second=0, microsecond=0)
    if size == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(second=0, microsecond=0)


def timeseries(r: Range, bucket: str = "hour") -> dict:
    with SessionLocal() as s:
        counts = s.execute(select(TrafficCount.bucket, TrafficCount.cls, TrafficCount.count)
                           .where(*r.f(TrafficCount.bucket, TrafficCount.camera_id))).all()
        incs = s.execute(select(Incident.occurred_at, Incident.type)
                         .where(*r.f(Incident.occurred_at, Incident.camera_id)).where(Incident.status != "dismissed")).all()
    rows: dict[datetime, dict] = {}

    def row(b):
        return rows.setdefault(b, {"start": b.isoformat(), "vehicles": 0, "pedestrian": 0, "events": 0,
                                   **{k: 0 for k in VEHICLE_KEYS}, "by_type": defaultdict(int)})

    for b, cls, n in counts:
        rw = row(_bucket(b, bucket))
        rw[cls] = rw.get(cls, 0) + n
        if cls in VEHICLE_KEYS:
            rw["vehicles"] += n
    for at, etype in incs:
        rw = row(_bucket(at, bucket))
        rw["events"] += 1
        rw["by_type"][etype] += 1
    out = []
    for b in sorted(rows):
        rw = rows[b]
        rw["by_type"] = dict(rw["by_type"])
        out.append(rw)
    return {"bucket": bucket, "buckets": out}


def zone_stats(r: Range) -> list[dict]:
    cams = {c.id: c for c in list_camera_configs() if not r.camera or c.id == r.camera}
    with SessionLocal() as s:
        ev_rows = s.execute(
            select(Incident.camera_id, Incident.zone_id, Incident.type, Incident.severity, func.count())
            .where(*r.f(Incident.occurred_at, Incident.camera_id)).where(Incident.status != "dismissed")
            .group_by(Incident.camera_id, Incident.zone_id, Incident.type, Incident.severity)).all()
        tracks = s.execute(select(TrackRecord.camera_id, TrackRecord.zones, TrackRecord.cls)
                           .where(*r.f(TrackRecord.first_seen, TrackRecord.camera_id))).all()
        samples = s.execute(
            select(ZoneSample.camera_id, ZoneSample.zone_id, func.avg(ZoneSample.vehicles_avg),
                   func.max(ZoneSample.vehicles_avg), func.avg(ZoneSample.speed_avg))
            .where(*r.f(ZoneSample.bucket, ZoneSample.camera_id)).group_by(ZoneSample.camera_id, ZoneSample.zone_id)).all()

    ev: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for cam, zid, etype, sev, n in ev_rows:
        ev[(cam, zid)][etype][sev] += n
    vol: dict[tuple, int] = defaultdict(int)
    peds: dict[tuple, int] = defaultdict(int)
    for cam, zones, cls in tracks:
        for zid in zones or []:
            if cls in VEHICLE_KEYS:
                vol[(cam, zid)] += 1
            elif cls == "pedestrian":
                peds[(cam, zid)] += 1
    occ = {(c, z): (a, m, sp) for c, z, a, m, sp in samples}

    out = []
    for cam in cams.values():
        for z in cam.zones:
            key = (cam.id, z.id)
            counts = {k: dict(v) for k, v in ev.get(key, {}).items()}
            loc = z.location or cam.location
            a, m, sp = occ.get(key, (None, None, None))
            out.append({
                "id": z.id, "camera_id": cam.id, "camera_name": cam.name, "name": z.name, "type": z.type,
                "lat": loc.lat if loc else None, "lng": loc.lng if loc else None,
                "polygon": z.polygon,
                "vehicles": vol.get(key, 0), "pedestrians": peds.get(key, 0),
                "occupancy_avg": round(a, 2) if a is not None else None,
                "occupancy_max": round(m, 2) if m is not None else None,
                "speed_avg_mps": round(sp, 2) if sp is not None else None,
                "events": {k: sum(v.values()) for k, v in counts.items()},
                "events_total": sum(sum(v.values()) for v in counts.values()),
                "risk": risk_score(counts, vol.get(key, 0)),
            })
    return out


def forecast(camera: Optional[str] = None, day: Optional[date] = None) -> dict:
    """Hour-of-day statistical baseline: mean vehicles per hour over the observed history.

    This is deliberately simple (spec §15: statistical baseline first). Hours never observed
    are reported as null rather than guessed.
    """
    with SessionLocal() as s:
        q = select(TrafficCount.bucket, TrafficCount.cls, TrafficCount.count)
        if camera:
            q = q.where(TrafficCount.camera_id == camera)
        rows = s.execute(q).all()
    per_day_hour: dict[tuple[date, int], int] = defaultdict(int)
    minutes_seen: dict[tuple[date, int], set] = defaultdict(set)
    for b, cls, n in rows:
        if cls in VEHICLE_KEYS:
            per_day_hour[(b.date(), b.hour)] += n
        minutes_seen[(b.date(), b.hour)].add(b.minute)
    by_hour: dict[int, list[float]] = defaultdict(list)
    for (d, h), mins in minutes_seen.items():
        # Scale partially observed hours to a full-hour rate.
        by_hour[h].append(per_day_hour.get((d, h), 0) * 60.0 / max(1, len(mins)))
    hours = []
    for h in range(24):
        vals = by_hour.get(h, [])
        hours.append({"hour": h, "expected_vehicles": round(sum(vals) / len(vals)) if vals else None,
                      "samples": len(vals)})
    known = [x for x in hours if x["expected_vehicles"] is not None]
    window = None
    if known:
        peak = max(x["expected_vehicles"] for x in known)
        hot = [x["hour"] for x in known if x["expected_vehicles"] >= 0.8 * peak and peak > 0]
        if hot:
            # longest contiguous run of hot hours
            runs, cur = [], [hot[0]]
            for h in hot[1:]:
                if h == cur[-1] + 1:
                    cur.append(h)
                else:
                    runs.append(cur)
                    cur = [h]
            runs.append(cur)
            best = max(runs, key=len)
            window = {"start": f"{best[0]:02d}:00", "end": f"{(best[-1] + 1) % 24:02d}:00"}
    days = len({d for d, _ in minutes_seen})
    return {"method": "hour-of-day mean of observed vehicle volume (scaled to full hours)",
            "days_of_history": days, "hours": hours, "expected_congestion_window": window,
            "for_date": (day or date.today()).isoformat()}
