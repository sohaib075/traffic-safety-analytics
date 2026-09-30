"""RoadGuard AI REST + WebSocket API."""
from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import cv2
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import analyst, analytics, auth, nlq, reports, settings
from .auth import Principal, audit, current_user, require
from .camera_config import CameraConfig, camera_config_path, list_camera_configs, load_camera_config, save_camera_config
from .accounts_api import router as accounts_router
from .db import AuditLog, Incident, Job, SessionLocal, TrackRecord, init_db
from .jobs import hub, jobs
from .pipeline.rules import EVENT_LABELS
from .pipeline.runner import incident_to_dict

log = logging.getLogger("roadguard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    auth.seed_users()
    hub.loop = asyncio.get_running_loop()
    with SessionLocal() as s:  # jobs interrupted by a restart
        for job in s.query(Job).filter(Job.status.in_(["queued", "running"])).all():
            job.status, job.error = "failed", "interrupted by server restart"
        s.commit()
    yield


app = FastAPI(title="RoadGuard AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", ""))
    except ValueError:
        raise HTTPException(400, f"Bad datetime: {v}")


def _range(start: Optional[str], end: Optional[str], camera: Optional[str]) -> analytics.Range:
    return analytics.Range(_dt(start), _dt(end), camera or None)


def _csv(v: Optional[str]) -> Optional[list[str]]:
    return [x for x in v.split(",") if x] if v else None


# Accounts: /api/auth/* and /api/users/* live in accounts_api.py
app.include_router(accounts_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "running_jobs": jobs.running(), "event_types": EVENT_LABELS}


# --------------------------------------------------------------------------- cameras
def _latest_job(camera_id: str) -> Optional[Job]:
    with SessionLocal() as s:
        return s.query(Job).filter_by(camera_id=camera_id).order_by(Job.id.desc()).first()


def _display_name(source: str) -> str:
    """Uploaded files are stored as '<8 hex>_<original name>'; show the original name."""
    name = Path(source).name
    head, _, rest = name.partition("_")
    return rest if rest and len(head) == 8 and all(c in "0123456789abcdef" for c in head) else name


def _job_dict(j: Job) -> dict:
    return {"id": j.id, "camera_id": j.camera_id, "source": _display_name(j.source), "status": j.status,
            "progress": j.progress, "video_start": j.video_start.isoformat(), "fps": j.fps,
            "total_frames": j.total_frames, "frames_processed": j.frames_processed, "proc_fps": j.proc_fps,
            "annotated_url": f"/evidence/{j.annotated_video}" if j.annotated_video and j.status in ("done", "cancelled") else None,
            "summary": j.summary, "error": j.error, "created_at": j.created_at.isoformat(),
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "live": jobs.live.get(j.id)}


@app.get("/api/cameras")
def cameras(user: Principal = Depends(require("view"))):
    out = []
    running = set(jobs.running())
    for c in list_camera_configs():
        j = _latest_job(c.id)
        out.append({"id": c.id, "name": c.name, "location": c.location.model_dump() if c.location else None,
                    "zones": [{"id": z.id, "name": z.name, "type": z.type} for z in c.zones],
                    "calibrated": c.calibration.has_homography,
                    "helmet_enabled": bool(c.rules.helmet.enabled and c.rules.helmet.model),
                    "live": bool(j and j.id in running), "latest_job": _job_dict(j) if j else None})
    return out


@app.get("/api/cameras/{camera_id}/config")
def get_camera_config(camera_id: str, user: Principal = Depends(require("view"))):
    p = camera_config_path(camera_id)
    if not p.exists():
        raise HTTPException(404, "Unknown camera")
    return load_camera_config(p).model_dump(mode="json", exclude_none=True)


@app.put("/api/cameras/{camera_id}/config")
def put_camera_config(camera_id: str, cfg: CameraConfig, user: Principal = Depends(require("configure"))):
    if cfg.id != camera_id:
        raise HTTPException(400, "Camera id mismatch")
    save_camera_config(cfg)
    audit(user, "camera_config_update", camera_id)
    return cfg.model_dump(mode="json")


@app.post("/api/cameras")
def create_camera(cfg: CameraConfig, user: Principal = Depends(require("configure"))):
    if camera_config_path(cfg.id).exists():
        raise HTTPException(409, "Camera already exists")
    save_camera_config(cfg)
    audit(user, "camera_create", cfg.id)
    return cfg.model_dump(mode="json")


@app.get("/api/cameras/{camera_id}/frame")
def camera_frame(camera_id: str, user: Principal = Depends(require("view"))):
    """Clean (un-annotated) first frame of the most recent source, for the zone editor."""
    j = _latest_job(camera_id)
    if j is None:
        raise HTTPException(404, "No video processed for this camera yet")
    cap = cv2.VideoCapture(j.source)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(404, "Source video not readable")
    return Response(cv2.imencode(".jpg", frame)[1].tobytes(), media_type="image/jpeg")


# --------------------------------------------------------------------------- jobs
@app.post("/api/jobs")
async def submit_job(
    camera_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    video_start: Optional[str] = Form(None),
    realtime: bool = Form(False),
    max_seconds: Optional[float] = Form(None),
    user: Principal = Depends(require("process")),
):
    cfg_path = camera_config_path(camera_id)
    if not cfg_path.exists():
        raise HTTPException(404, "Unknown camera")
    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower() or ".mp4"
        if suffix not in (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"):
            raise HTTPException(400, "Unsupported video type")
        dest = settings.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
        source = str(dest)
    elif path:
        # Local files or stream URLs (rtsp/http) for operators running the stack on-prem.
        if path.startswith(("rtsp://", "http://", "https://")):
            source = path
        else:
            p = Path(path)
            p = p if p.is_absolute() else settings.BACKEND_DIR / p
            if not p.is_file():
                raise HTTPException(400, "Path does not exist")
            source = str(p.resolve())
    else:
        raise HTTPException(400, "Provide a file upload or a path")
    job_id = jobs.submit(load_camera_config(cfg_path), source, _dt(video_start), realtime=realtime, max_seconds=max_seconds)
    audit(user, "job_submit", f"job {job_id} camera {camera_id} source {Path(source).name}")
    return {"job_id": job_id}


VIDEO_SUFFIXES = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".ts")

# "Analyze video" presets for the generic uploads profile.
QUALITY = {
    "fast": {"model": "yolov8n.pt", "helmet_every": 0.2, "stride": lambda fps: 3 if fps >= 40 else 2 if fps >= 20 else 1},
    "accurate": {"model": "yolo11s.pt", "helmet_every": 0.1, "stride": lambda fps: 2 if fps >= 40 else 1},
}


@app.post("/api/analyze")
async def analyze_video(
    file: UploadFile = File(...),
    quality: str = Form("accurate"),
    conflicts: bool = Form(False),
    video_start: Optional[str] = Form(None),
    user: Principal = Depends(require("process")),
):
    """Analyse any uploaded video with the generic 'uploads' profile — no camera setup needed.

    Near-miss / pedestrian-conflict detection is opt-in here: on uncalibrated footage of unknown
    geometry, image distances say little about real distances and those rules over-fire.
    """
    if quality not in QUALITY:
        raise HTTPException(400, "quality must be 'fast' or 'accurate'")
    name = Path(file.filename or "video.mp4").name
    if Path(name).suffix.lower() not in VIDEO_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type. Use one of: {', '.join(VIDEO_SUFFIXES)}")
    dest = settings.UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{name}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f, length=4 * 1024 * 1024)

    cap = cv2.VideoCapture(str(dest))
    ok, _ = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not ok:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Could not read any frames from this file — is it a valid video?")

    preset = QUALITY[quality]
    base = load_camera_config(camera_config_path("uploads"))
    rules = base.rules.model_copy(update={
        "helmet": base.rules.helmet.model_copy(update={"check_every_s": preset["helmet_every"]}),
        "near_miss": base.rules.near_miss.model_copy(update={"enabled": conflicts}),
        "ped_conflict": base.rules.ped_conflict.model_copy(update={"enabled": conflicts}),
    })
    cfg = base.model_copy(update={"model": preset["model"], "frame_stride": preset["stride"](fps), "rules": rules})

    job_id = jobs.submit(cfg, str(dest), _dt(video_start))
    audit(user, "analyze_upload", f"job {job_id} {name} ({w}x{h}, {frames / max(fps, 1):.0f}s, {quality})")
    return {"job_id": job_id, "video": {"name": name, "width": w, "height": h, "fps": round(fps, 2),
                                        "duration_s": round(frames / max(fps, 1), 1), "frame_stride": cfg.frame_stride}}


@app.get("/api/jobs")
def list_jobs(limit: int = 50, camera: Optional[str] = None, user: Principal = Depends(require("view"))):
    with SessionLocal() as s:
        q = s.query(Job)
        if camera:
            q = q.filter(Job.camera_id == camera)
        rows = q.order_by(Job.id.desc()).limit(limit).all()
    return [_job_dict(j) for j in rows]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, user: Principal = Depends(require("view"))):
    with SessionLocal() as s:
        j = s.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Unknown job")
    return _job_dict(j)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: int, user: Principal = Depends(require("process"))):
    if not jobs.cancel(job_id):
        raise HTTPException(404, "Job not running")
    audit(user, "job_cancel", str(job_id))
    return {"ok": True}


# --------------------------------------------------------------------------- live
@app.get("/api/live/{camera_id}.mjpg")
def live_mjpeg(camera_id: str, user: Principal = Depends(require("view"))):
    stop = threading.Event()

    def gen():
        try:
            yield from hub.mjpeg(camera_id, stop)
        finally:
            stop.set()

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = ""):
    p = auth.principal_from_token(token) if settings.AUTH_ENABLED else None
    if settings.AUTH_ENABLED and (p is None or p.must_change_password):
        await websocket.close(code=4401)
        return
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive pings from client
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)


# --------------------------------------------------------------------------- evidence
@app.get("/evidence/{path:path}")
def evidence(path: str, user: Principal = Depends(require("view"))):
    full = (settings.EVIDENCE_DIR / path).resolve()
    if settings.EVIDENCE_DIR.resolve() not in full.parents or not full.is_file():
        raise HTTPException(404, "Not found")
    if full.suffix == ".mp4" and not user.can("investigate") and full.name != "annotated.mp4":
        raise HTTPException(403, "Evidence clips require the operator or admin role")
    return FileResponse(full)


# --------------------------------------------------------------------------- analytics
@app.get("/api/stats/extent")
def stats_extent(user: Principal = Depends(require("view"))):
    return analytics.data_extent()


@app.get("/api/stats/summary")
def stats_summary(start: Optional[str] = None, end: Optional[str] = None, camera: Optional[str] = None,
                  user: Principal = Depends(require("view"))):
    return analytics.summary(_range(start, end, camera))


@app.get("/api/stats/timeseries")
def stats_timeseries(start: Optional[str] = None, end: Optional[str] = None, camera: Optional[str] = None,
                     bucket: str = Query("hour", pattern="^(minute|15min|hour|day)$"),
                     user: Principal = Depends(require("view"))):
    return analytics.timeseries(_range(start, end, camera), bucket)


@app.get("/api/stats/zones")
def stats_zones(start: Optional[str] = None, end: Optional[str] = None, camera: Optional[str] = None,
                user: Principal = Depends(require("view"))):
    return analytics.zone_stats(_range(start, end, camera))


@app.get("/api/stats/forecast")
def stats_forecast(camera: Optional[str] = None, user: Principal = Depends(require("view"))):
    return analytics.forecast(camera)


@app.get("/api/stats/risk-config")
def risk_config(user: Principal = Depends(require("view"))):
    return analytics.risk_config()


# --------------------------------------------------------------------------- incidents
@app.get("/api/incidents")
def list_incidents(
    start: Optional[str] = None, end: Optional[str] = None, camera: Optional[str] = None,
    types: Optional[str] = None, severities: Optional[str] = None, zone: Optional[str] = None,
    vehicle_class: Optional[str] = None, status: Optional[str] = None,
    hour_from: Optional[int] = None, hour_to: Optional[int] = None, q: Optional[str] = None,
    limit: int = Query(50, le=500), offset: int = 0, order: str = "desc", job: Optional[int] = None,
    user: Principal = Depends(require("view")),
):
    types_l, sev_l = _csv(types), _csv(severities)
    parsed = None
    if q:  # natural-language search fills in any filter not set explicitly
        parsed = nlq.parse(q)
        types_l = types_l or parsed["types"]
        sev_l = sev_l or parsed["severities"]
        hour_from = hour_from if hour_from is not None else parsed["hour_from"]
        hour_to = hour_to if hour_to is not None else parsed["hour_to"]
    total, rows = analytics.search_incidents(
        _range(start, end, camera), types=types_l, severities=sev_l, zone=zone, vehicle_class=vehicle_class,
        status=_csv(status), hour_from=hour_from, hour_to=hour_to, limit=limit, offset=offset, order=order, job=job)
    return {"total": total, "items": [incident_to_dict(i) for i in rows], "parsed_query": parsed}


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: int, user: Principal = Depends(require("view"))):
    with SessionLocal() as s:
        inc = s.get(Incident, incident_id)
        if not inc:
            raise HTTPException(404, "Unknown incident")
        tracks = s.query(TrackRecord).filter(TrackRecord.job_id == inc.job_id,
                                             TrackRecord.track_id.in_(inc.track_ids or [-1])).all()
    d = incident_to_dict(inc)
    d["journeys"] = [_journey(t) for t in tracks]
    if not user.can("investigate"):
        d["clip_url"] = None
    audit(user, "incident_view", str(incident_id))
    return d


class IncidentPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


@app.patch("/api/incidents/{incident_id}")
def patch_incident(incident_id: int, body: IncidentPatch, user: Principal = Depends(require("review"))):
    if body.status and body.status not in ("new", "confirmed", "dismissed"):
        raise HTTPException(400, "Bad status")
    with SessionLocal() as s:
        inc = s.get(Incident, incident_id)
        if not inc:
            raise HTTPException(404, "Unknown incident")
        if body.status:
            inc.status = body.status
        if body.notes is not None:
            inc.notes = body.notes
        s.commit()
        d = incident_to_dict(inc)
    audit(user, "incident_review", f"{incident_id} status={body.status}")
    hub.publish("incident", {**d, "_update": True})
    return d


def _journey(t: TrackRecord) -> dict:
    cfg_path = camera_config_path(t.camera_id)
    names = {}
    if cfg_path.exists():
        cfg = load_camera_config(cfg_path)
        names = {z.id: z.name for z in cfg.zones}
    return {"job_id": t.job_id, "track_id": t.track_id, "cls": t.cls, "camera_id": t.camera_id,
            "first_seen": t.first_seen.isoformat(), "last_seen": t.last_seen.isoformat(),
            "video_t0": t.video_t0, "video_t1": t.video_t1,
            "route": [{"zone_id": z, "name": names.get(z, z)} for z in t.zones],
            "path": t.path, "max_speed_mps": t.max_speed, "events": t.events, "helmet": t.helmet}


@app.get("/api/tracks/{job_id}/{track_id}")
def get_track(job_id: int, track_id: int, user: Principal = Depends(require("investigate"))):
    with SessionLocal() as s:
        t = s.query(TrackRecord).filter_by(job_id=job_id, track_id=track_id).one_or_none()
    if not t:
        raise HTTPException(404, "Unknown track")
    return _journey(t)


# --------------------------------------------------------------------------- reports + analyst
@app.get("/api/reports/daily.pdf")
def daily_report(day: Optional[str] = Query(None, alias="date"), camera: Optional[str] = None,
                 user: Principal = Depends(require("report"))):
    d = date.fromisoformat(day) if day else analyst.reference_day()
    pdf = reports.build_daily_report(d, camera)
    audit(user, "report_daily", d.isoformat())
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="roadguard-report-{d.isoformat()}.pdf"'})


class AskIn(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/analyst")
def ask(body: AskIn, user: Principal = Depends(require("view"))):
    res = analyst.ask(body.question, body.history)
    if not user.can("investigate"):
        for e in res["evidence"]:
            e["clip_url"] = None
    return res


# --------------------------------------------------------------------------- admin
@app.get("/api/audit")
def audit_log(limit: int = 200, user: Principal = Depends(require("manage_users"))):
    with SessionLocal() as s:
        rows = s.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [{"ts": r.ts.isoformat(), "username": r.username, "action": r.action, "detail": r.detail} for r in rows]
