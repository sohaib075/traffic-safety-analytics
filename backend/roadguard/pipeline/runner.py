"""Video → detections → tracks → events → evidence → database."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .. import settings
from ..camera_config import CameraConfig
from ..db import Camera, Incident, Job, SessionLocal, TrackRecord, TrafficCount, ZoneSample
from .annotate import Annotator, blur_boxes, blur_heads, draw_event_snapshot
from .evidence import EvidenceRecorder, VideoSink
from .geometry import SceneGeometry
from .helmet import HelmetChecker
from .rules import Event, RuleEngine
from .tracking import GroupedTracker
from .tracks import Track, TrackManager

log = logging.getLogger(__name__)

MIN_TRACK_OBS = 5  # tracks shorter than this are treated as detector noise


def _backend_path(p: str) -> str:
    """Resolve a relative model/tracker path against backend/ if it exists there.

    Bare names like "yolov8n.pt" or "bytetrack.yaml" that are not local files are passed through,
    so Ultralytics can download the weights or use its bundled tracker config.
    """
    path = Path(p)
    if path.is_absolute():
        return str(path)
    local = settings.BACKEND_DIR / path
    return str(local) if local.exists() else p


def _minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def incident_to_dict(inc: Incident) -> dict:
    return {
        "id": inc.id,
        "job_id": inc.job_id,
        "camera_id": inc.camera_id,
        "type": inc.type,
        "severity": inc.severity,
        "zone_id": inc.zone_id,
        "zone_name": inc.zone_name,
        "occurred_at": inc.occurred_at.isoformat(),
        "video_t": inc.video_t,
        "track_ids": inc.track_ids,
        "classes": inc.classes,
        "metrics": inc.metrics,
        "confidence": inc.confidence,
        "description": inc.description,
        "snapshot_url": f"/evidence/{inc.snapshot}" if inc.snapshot else None,
        "clip_url": f"/evidence/{inc.clip}" if inc.clip and inc.clip_ready else None,
        "clip_ready": inc.clip_ready,
        "status": inc.status,
        "notes": inc.notes,
    }


class VideoProcessor:
    def __init__(
        self,
        cfg: CameraConfig,
        source: str,
        job_id: int,
        video_start: datetime,
        save_annotated: bool = True,
        max_seconds: Optional[float] = None,
        on_incident: Optional[Callable[[dict], None]] = None,
        on_progress: Optional[Callable[[dict], None]] = None,
        on_frame: Optional[Callable[[bytes], None]] = None,
        realtime: bool = False,
        stop_flag: Optional[threading.Event] = None,
    ):
        self.cfg = cfg
        self.source = source
        self.job_id = job_id
        self.video_start = video_start
        self.save_annotated = save_annotated
        self.max_seconds = max_seconds
        self.on_incident = on_incident or (lambda d: None)
        self.on_progress = on_progress or (lambda d: None)
        self.on_frame = on_frame
        self.realtime = realtime
        self.stop_flag = stop_flag or threading.Event()

        self.counts: dict[tuple[datetime, str], int] = defaultdict(int)
        self.zone_acc: dict[tuple[datetime, str], list] = defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0])
        self.class_totals: dict[str, int] = defaultdict(int)
        self.event_totals: dict[str, int] = defaultdict(int)
        self.helmet_stats = {"checked": 0, "compliant": 0, "violations": 0}
        self._lock = threading.Lock()
        self._clip_ids: dict[str, int] = {}
        self._current_bucket: Optional[datetime] = None

    # ------------------------------------------------------------------ setup
    def _load_model(self):
        from ultralytics import YOLO

        model = YOLO(_backend_path(self.cfg.model or settings.MODEL_PATH))
        name_to_id = {n: i for i, n in model.names.items()}
        class_ids = [name_to_id[c] for c in self.cfg.classes if c in name_to_id]
        return model, class_ids

    def _wall(self, t: float) -> datetime:
        return self.video_start + timedelta(seconds=t)

    # ------------------------------------------------------------------ main loop
    def run(self) -> dict:
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source: {self.source}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if fps <= 1 or fps > 240:
            fps = 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        stride = max(1, self.cfg.frame_stride)
        eff_fps = fps / stride

        model, class_ids = self._load_model()
        person_ids = [i for i, n in model.names.items() if n == "person" and i in class_ids]
        grouped = GroupedTracker(_backend_path(self.cfg.tracker),
                                 [person_ids, [i for i in class_ids if i not in person_ids]])
        calib = self.cfg.calibration
        self.scale_note = None
        if calib.auto_scale and not calib.has_homography:
            est = self._estimate_scene_width(cap, model, total, width)
            if est:
                calib = calib.model_copy(update={"approx_scene_width_m": est})
                self.scale_note = f"auto scale: frame ≈ {est:.0f} m wide (from car sizes)"
        geom = SceneGeometry(calib, width, height)
        tracks = TrackManager(geom)
        engine = RuleEngine(self.cfg, geom)
        annot = Annotator(self.cfg, geom, engine)
        helmet = HelmetChecker(self.cfg.rules.helmet, settings.DEVICE)
        plate_model = None
        if self.cfg.privacy.plate_model:
            from ultralytics import YOLO

            plate_model = YOLO(self.cfg.privacy.plate_model)

        ev_dir = settings.EVIDENCE_DIR / self.cfg.id / f"job{self.job_id}"
        recorder = EvidenceRecorder(ev_dir, eff_fps, self.cfg.evidence.pre_s, self.cfg.evidence.post_s, self.cfg.evidence.max_width)
        annotated_sink = None
        annotated_rel = None
        if self.save_annotated:
            annotated_rel = f"{self.cfg.id}/job{self.job_id}/annotated.mp4"
            w = min(width, 1280)
            h = int(height * w / width) // 2 * 2
            annotated_sink = VideoSink(settings.EVIDENCE_DIR / annotated_rel, eff_fps, (w, h))

        self._update_job(status="running", fps=fps, total_frames=total, annotated_video=annotated_rel)

        frame_idx = -1
        processed = 0
        t0 = time.perf_counter()
        last_flush = 0.0
        last_progress = 0.0
        live_counts: dict[str, int] = defaultdict(int)
        max_frames = int(self.max_seconds * fps) if self.max_seconds else None

        try:
            while not self.stop_flag.is_set():
                frame_idx += 1
                if max_frames and frame_idx >= max_frames:
                    break
                if frame_idx % stride:
                    if not cap.grab():
                        break
                    continue
                ok, frame = cap.read()
                if not ok:
                    break
                t = frame_idx / fps
                loop_start = time.perf_counter()

                res = model.predict(
                    frame, classes=class_ids, conf=self.cfg.conf_threshold, imgsz=self.cfg.imgsz,
                    device=settings.DEVICE, verbose=False,
                )[0]
                dets = [(tid, model.names[c], conf, box)
                        for tid, c, conf, box in grouped.update(res.boxes.cpu().numpy(), frame)]

                retired = tracks.update(t, frame_idx, dets)
                for tr in retired:
                    engine.forget(tr.track_id)
                    self._retire(tr)
                active = tracks.active()
                self._mark_riders(active)

                events = engine.process(t, frame_idx, frame, active)
                helmet_events = helmet.process(t, frame_idx, frame, active)
                by_tid = {tr.track_id: tr for tr in active}
                for ev in helmet_events:  # the helmet checker has no scene zones; borrow the rule engine's
                    moto = by_tid.get(ev.track_ids[0])
                    if moto is not None and ev.zone_id is None:
                        ev.zone_id, ev.zone_name = engine._zone_of(moto)
                events += helmet_events

                # Privacy first, then overlays.
                if self.cfg.privacy.blur_heads:
                    blur_heads(frame, active)
                if plate_model is not None:
                    pr = plate_model.predict(frame, conf=0.3, verbose=False, device=settings.DEVICE)[0]
                    if pr.boxes is not None:
                        blur_boxes(frame, pr.boxes.xyxy.cpu().numpy())

                for ev in events:
                    annot.flag(t, ev.track_ids, ev.label)
                live_counts.clear()
                for tr in active:
                    live_counts["pedestrian" if tr.is_pedestrian else "rider" if tr.is_person else tr.cls] += 1
                img = annot.draw(frame, t, active, dict(live_counts))

                by_id = {tr.track_id: tr for tr in active}
                for ev in events:
                    snap = draw_event_snapshot(img.copy(), by_id, ev.track_ids, ev.type)
                    self._record_event(ev, snap, recorder)
                recorder.push(img)
                if annotated_sink:
                    annotated_sink.write(img)
                if self.on_frame:
                    small = cv2.resize(img, (min(960, img.shape[1]), int(img.shape[0] * min(960, img.shape[1]) / img.shape[1])))
                    ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        self.on_frame(jpg.tobytes())

                self._sample_zones(t, engine)
                processed += 1

                if t - last_flush >= 10.0:
                    self._flush_counts()
                    last_flush = t
                now = time.perf_counter()
                if now - last_progress >= 1.0:
                    last_progress = now
                    prog = {
                        "job_id": self.job_id,
                        "progress": round(frame_idx / total, 4) if total else None,
                        "frames_processed": processed,
                        "proc_fps": round(processed / (now - t0), 2),
                        "video_t": round(t, 1),
                        "live": {"objects": dict(live_counts), "zones": engine.zone_live,
                                 "signals": engine.signal_state},
                    }
                    self._update_job(progress=prog["progress"] or 0.0, frames_processed=processed, proc_fps=prog["proc_fps"])
                    self.on_progress(prog)
                if self.realtime:
                    delay = stride / fps - (time.perf_counter() - loop_start)
                    if delay > 0:
                        time.sleep(delay)
        finally:
            cap.release()
            for tr in tracks.flush():
                self._retire(tr)
            recorder.close()
            if annotated_sink:
                annotated_sink.close()
            self._flush_counts()
            self._flush_zone_samples(final=True)

        elapsed = time.perf_counter() - t0
        summary = {
            "frames_processed": processed,
            "video_seconds": round((frame_idx + 1) / fps, 1),
            "processing_seconds": round(elapsed, 1),
            "proc_fps": round(processed / elapsed, 2) if elapsed else None,
            "calibrated": geom.calibrated,
            "scale_note": self.scale_note,
            "rules_enabled": {
                "near_miss": self.cfg.rules.near_miss.enabled,
                "ped_conflict": self.cfg.rules.ped_conflict.enabled,
                "red_light": self.cfg.rules.red_light.enabled and bool(self.cfg.stop_lines),
                "wrong_way": self.cfg.rules.wrong_way.enabled and bool(self.cfg.lanes),
                "illegal_stop": self.cfg.rules.illegal_stop.enabled and any(z.type == "no_stopping" for z in self.cfg.zones),
                "congestion": self.cfg.rules.congestion.enabled,
                "helmet_violation": helmet.active,
            },
            "resolution": [width, height],
            "source_fps": round(fps, 2),
            "frame_stride": stride,
            "classes": dict(self.class_totals),
            "events": dict(self.event_totals),
            "line_counts": engine.line_counts,
            "helmet": {**self.helmet_stats, "enabled": helmet.active},
        }
        self._update_job(
            status="cancelled" if self.stop_flag.is_set() else "done",
            progress=1.0, frames_processed=processed, summary=summary, finished_at=datetime.now(),
        )
        return summary

    # ------------------------------------------------------------------ helpers
    def _estimate_scene_width(self, cap, model, total: Optional[int], width: int, samples: int = 12) -> Optional[float]:
        """Uniform metres-per-pixel from the median car width (≈1.8 m) over a few sampled frames.

        Crude — it ignores perspective — but far better than a fixed guess for unknown footage.
        Leaves the capture rewound to the first frame.
        """
        car_id = next((i for i, n in model.names.items() if n == "car"), None)
        if car_id is None:
            return None
        n = total or 300
        widths = []
        for k in range(samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((k + 0.5) * n / samples))
            ok, frame = cap.read()
            if not ok:
                continue
            r = model.predict(frame, classes=[car_id], conf=0.4, imgsz=self.cfg.imgsz, device=settings.DEVICE, verbose=False)[0]
            for x1, y1, x2, y2 in r.boxes.xyxy.tolist():
                # Side-on cars are ~4.5 m long, so use the smaller box side as the ~1.8 m width.
                widths.append(min(x2 - x1, y2 - y1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        if len(widths) < 3:
            return None
        m_per_px = 1.8 / float(np.median(widths))
        return float(np.clip(width * m_per_px, 5.0, 400.0))

    def _mark_riders(self, active: list[Track]) -> None:
        from .rules import _overlap_ratio

        two = [tr for tr in active if tr.cls in ("motorcycle", "bicycle")]
        for p in active:
            if p.is_person and any(_overlap_ratio(p.last.bbox, m.last.bbox) > 0.3 for m in two):
                p.rider_frames += 1

    def _record_event(self, ev: Event, snapshot: np.ndarray, recorder: EvidenceRecorder) -> None:
        key = f"{ev.type}_{uuid.uuid4().hex[:10]}"
        snap_name, clip_name = recorder.capture(key, snapshot, on_clip_done=lambda k: self._clip_done(k))
        rel = f"{self.cfg.id}/job{self.job_id}"
        with SessionLocal() as s:
            inc = Incident(
                job_id=self.job_id, camera_id=self.cfg.id, type=ev.type, severity=ev.severity,
                zone_id=ev.zone_id, zone_name=ev.zone_name, occurred_at=self._wall(ev.t), video_t=round(ev.t, 2),
                track_ids=ev.track_ids, classes=ev.classes, metrics=ev.metrics, confidence=ev.confidence,
                description=ev.description, snapshot=f"{rel}/{snap_name}", clip=f"{rel}/{clip_name}", clip_ready=False,
            )
            s.add(inc)
            s.commit()
            self._clip_ids[key] = inc.id
            payload = incident_to_dict(inc)
        self.event_totals[ev.type] += 1
        log.info("event %s %s t=%.1f tracks=%s", ev.type, ev.severity, ev.t, ev.track_ids)
        self.on_incident(payload)

    def _clip_done(self, key: str) -> None:
        inc_id = self._clip_ids.pop(key, None)
        if inc_id is None:
            return
        with SessionLocal() as s:
            inc = s.get(Incident, inc_id)
            if inc:
                inc.clip_ready = True
                s.commit()
                self.on_incident({**incident_to_dict(inc), "_update": True})

    def _retire(self, tr: Track) -> None:
        if tr.n_obs < MIN_TRACK_OBS:
            return
        if tr.is_person and not tr.is_pedestrian:
            return  # riders are counted via their motorcycle / bicycle
        cls = "pedestrian" if tr.is_person else tr.cls
        helmet = tr.helmet_label if tr.cls == "motorcycle" else None
        if helmet:
            self.helmet_stats["checked"] += 1
            self.helmet_stats["violations" if helmet == "no_helmet" else "compliant"] += 1
        with self._lock:
            self.counts[(_minute(self._wall(tr.first_t)), cls)] += 1
            self.class_totals[cls] += 1
        with SessionLocal() as s:
            s.add(TrackRecord(
                job_id=self.job_id, camera_id=self.cfg.id, track_id=tr.track_id, cls=cls,
                first_seen=self._wall(tr.first_t), last_seen=self._wall(tr.last_t),
                video_t0=round(tr.first_t, 2), video_t1=round(tr.last_t, 2), zones=tr.zones, path=tr.path,
                max_speed=round(tr.max_speed, 2), events=sorted(set(tr.events)), helmet=helmet,
            ))
            s.commit()

    def _flush_counts(self) -> None:
        with self._lock:
            pending = dict(self.counts)
            self.counts.clear()
        if not pending:
            return
        with SessionLocal() as s:
            for (bucket, cls), n in pending.items():
                row = s.query(TrafficCount).filter_by(job_id=self.job_id, bucket=bucket, cls=cls).one_or_none()
                if row:
                    row.count += n
                else:
                    s.add(TrafficCount(job_id=self.job_id, camera_id=self.cfg.id, bucket=bucket, cls=cls, count=n))
            s.commit()
        self._flush_zone_samples()

    def _sample_zones(self, t: float, engine: RuleEngine) -> None:
        bucket = _minute(self._wall(t))
        for zid, live in engine.zone_live.items():
            acc = self.zone_acc[(bucket, zid)]
            acc[0] += live["vehicles"]
            acc[1] += live["people"]
            if live["avg_speed_mps"] is not None:
                acc[2] += live["avg_speed_mps"]
                acc[4] += 1
            acc[3] += 1
        self._current_bucket = bucket

    def _flush_zone_samples(self, final: bool = False) -> None:
        current = self._current_bucket
        done = [k for k in self.zone_acc if final or k[0] != current]
        if not done:
            return
        with SessionLocal() as s:
            for key in done:
                vsum, psum, ssum, n, ns = self.zone_acc.pop(key)
                s.add(ZoneSample(
                    job_id=self.job_id, camera_id=self.cfg.id, zone_id=key[1], bucket=key[0],
                    vehicles_avg=round(vsum / max(1, n), 2), people_avg=round(psum / max(1, n), 2),
                    speed_avg=round(ssum / ns, 2) if ns else None,
                ))
            s.commit()

    def _update_job(self, **fields) -> None:
        with SessionLocal() as s:
            job = s.get(Job, self.job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            s.commit()


def create_job(cfg: CameraConfig, source: str, video_start: Optional[datetime] = None) -> int:
    with SessionLocal() as s:
        if s.get(Camera, cfg.id) is None:
            s.add(Camera(id=cfg.id, name=cfg.name,
                         lat=cfg.location.lat if cfg.location else None,
                         lng=cfg.location.lng if cfg.location else None))
        job = Job(camera_id=cfg.id, source=source, video_start=video_start or datetime.now(), status="queued")
        s.add(job)
        s.commit()
        return job.id
