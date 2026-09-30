"""SQLite (SQLAlchemy) storage for incidents, tracks, traffic counts and users."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import settings

settings.ensure_dirs()
engine = create_engine(settings.DB_URL, connect_args={"check_same_thread": False} if settings.DB_URL.startswith("sqlite") else {})

if settings.DB_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))  # admin | operator | analyst
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Bumped on password change / reset / "sign out everywhere" / disable → invalidates old tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    video_start: Mapped[datetime] = mapped_column(DateTime)  # wall-clock time of video t=0
    fps: Mapped[Optional[float]] = mapped_column(Float)
    total_frames: Mapped[Optional[int]] = mapped_column(Integer)
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    proc_fps: Mapped[Optional[float]] = mapped_column(Float)
    annotated_video: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))
    zone_id: Mapped[Optional[str]] = mapped_column(String(64))
    zone_name: Mapped[Optional[str]] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    video_t: Mapped[float] = mapped_column(Float)
    track_ids: Mapped[list[Any]] = mapped_column(default=list)
    classes: Mapped[list[Any]] = mapped_column(default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[Optional[str]] = mapped_column(Text)
    clip: Mapped[Optional[str]] = mapped_column(Text)
    clip_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | confirmed | dismissed
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_incident_time", "occurred_at"), Index("ix_incident_type", "type"))


class TrackRecord(Base):
    __tablename__ = "tracks"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    track_id: Mapped[int] = mapped_column(Integer)
    cls: Mapped[str] = mapped_column(String(32))
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    video_t0: Mapped[float] = mapped_column(Float)
    video_t1: Mapped[float] = mapped_column(Float)
    zones: Mapped[list[Any]] = mapped_column(default=list)
    path: Mapped[list[Any]] = mapped_column(default=list)  # [(t, nx, ny)]
    max_speed: Mapped[float] = mapped_column(Float, default=0.0)
    events: Mapped[list[Any]] = mapped_column(default=list)
    helmet: Mapped[Optional[str]] = mapped_column(String(16))  # helmet | no_helmet | unknown

    __table_args__ = (Index("ix_track_job_tid", "job_id", "track_id"), Index("ix_track_first", "first_seen"))


class TrafficCount(Base):
    """Unique road users first seen within a one-minute bucket."""

    __tablename__ = "traffic_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    bucket: Mapped[datetime] = mapped_column(DateTime)
    cls: Mapped[str] = mapped_column(String(32))  # car, motorcycle, ..., pedestrian
    count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_tc_bucket", "bucket"),)


class ZoneSample(Base):
    """Per-minute average occupancy/speed for a zone (congestion analytics)."""

    __tablename__ = "zone_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    zone_id: Mapped[str] = mapped_column(String(64))
    bucket: Mapped[datetime] = mapped_column(DateTime)
    vehicles_avg: Mapped[float] = mapped_column(Float)
    people_avg: Mapped[float] = mapped_column(Float)
    speed_avg: Mapped[Optional[float]] = mapped_column(Float)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    username: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()


# Columns added after the first release: (table, column, SQL type + default). create_all() does
# not alter existing tables, so older databases get them here.
_ADDED_COLUMNS = [
    ("users", "full_name", "VARCHAR(128) NOT NULL DEFAULT ''"),
    ("users", "active", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "last_login", "DATETIME"),
    ("users", "password_changed_at", "DATETIME"),
]


def _migrate() -> None:
    if not settings.DB_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, col, ddl in _ADDED_COLUMNS:
            cols = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
