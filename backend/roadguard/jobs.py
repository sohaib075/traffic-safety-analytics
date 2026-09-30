"""Background processing jobs and the live broadcast hub (WebSocket + MJPEG)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from typing import Optional

from fastapi import WebSocket

from .camera_config import CameraConfig
from .db import Job, SessionLocal
from .pipeline.runner import VideoProcessor, create_job

log = logging.getLogger(__name__)


class LiveHub:
    """Fan-out of events to WebSocket clients and latest frames to MJPEG viewers."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.frames: dict[str, bytes] = {}
        self.frame_cond = threading.Condition()
        self.frame_seq: dict[str, int] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _send_all(self, msg: str) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def publish(self, kind: str, data: dict) -> None:
        """Thread-safe publish from pipeline threads."""
        if self.loop is None:
            return
        msg = json.dumps({"kind": kind, "data": data}, default=str)
        asyncio.run_coroutine_threadsafe(self._send_all(msg), self.loop)

    def push_frame(self, camera_id: str, jpg: bytes) -> None:
        with self.frame_cond:
            self.frames[camera_id] = jpg
            self.frame_seq[camera_id] = self.frame_seq.get(camera_id, 0) + 1
            self.frame_cond.notify_all()

    def mjpeg(self, camera_id: str, stop: threading.Event):
        seen = -1
        while not stop.is_set():
            with self.frame_cond:
                self.frame_cond.wait_for(lambda: self.frame_seq.get(camera_id, 0) != seen or stop.is_set(), timeout=5)
                jpg = self.frames.get(camera_id)
                seen = self.frame_seq.get(camera_id, 0)
            if jpg is None:
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"


hub = LiveHub()


class JobManager:
    """Runs one processing thread per submitted video."""

    def __init__(self):
        self.threads: dict[int, threading.Thread] = {}
        self.stops: dict[int, threading.Event] = {}
        self.live: dict[int, dict] = {}

    def submit(self, cfg: CameraConfig, source: str, video_start: Optional[datetime] = None,
               realtime: bool = False, max_seconds: Optional[float] = None) -> int:
        job_id = create_job(cfg, source, video_start)
        stop = threading.Event()
        self.stops[job_id] = stop

        def on_progress(p: dict) -> None:
            self.live[job_id] = p
            hub.publish("progress", {**p, "camera_id": cfg.id})

        def run() -> None:
            try:
                proc = VideoProcessor(
                    cfg, source, job_id, video_start or datetime.now(), save_annotated=True,
                    max_seconds=max_seconds, realtime=realtime, stop_flag=stop,
                    on_incident=lambda d: hub.publish("incident", d),
                    on_progress=on_progress,
                    on_frame=lambda jpg: hub.push_frame(cfg.id, jpg),
                )
                summary = proc.run()
                hub.publish("job_done", {"job_id": job_id, "camera_id": cfg.id, "summary": summary})
            except Exception as e:  # surface failures on the job row
                log.exception("job %s failed", job_id)
                with SessionLocal() as s:
                    job = s.get(Job, job_id)
                    if job:
                        job.status, job.error, job.finished_at = "failed", str(e), datetime.now()
                        s.commit()
                hub.publish("job_done", {"job_id": job_id, "camera_id": cfg.id, "error": str(e)})
            finally:
                self.live.pop(job_id, None)

        th = threading.Thread(target=run, name=f"job-{job_id}", daemon=True)
        self.threads[job_id] = th
        th.start()
        return job_id

    def cancel(self, job_id: int) -> bool:
        ev = self.stops.get(job_id)
        if ev is None:
            return False
        ev.set()
        return True

    def running(self) -> list[int]:
        return [jid for jid, th in self.threads.items() if th.is_alive()]


jobs = JobManager()
