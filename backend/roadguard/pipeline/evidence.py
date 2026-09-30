"""Evidence capture: snapshot stills and short pre/post-event video clips.

Annotated frames are kept JPEG-compressed in a ring buffer so a clip can start a few
seconds *before* the event fired. Clips are encoded to browser-playable H.264 through the
ffmpeg binary bundled with imageio-ffmpeg, falling back to OpenCV if it is unavailable.
"""
from __future__ import annotations

import logging
import subprocess
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

try:
    import imageio_ffmpeg

    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:  # pragma: no cover - optional dependency
    FFMPEG = None


def _resize(img: np.ndarray, max_width: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= max_width:
        return img
    s = max_width / w
    return cv2.resize(img, (max_width, int(h * s) // 2 * 2), interpolation=cv2.INTER_AREA)


class VideoSink:
    """Minimal H.264 writer (ffmpeg pipe) with an OpenCV fallback."""

    def __init__(self, path: Path, fps: float, size: tuple[int, int]):
        self.path = path
        w, h = size
        self.proc = None
        self.cv = None
        if FFMPEG:
            cmd = [
                FFMPEG, "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(path),
            ]
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            self.cv = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        self.size = size

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[1] != self.size[0] or frame.shape[0] != self.size[1]:
            frame = cv2.resize(frame, self.size)
        if self.proc:
            try:
                self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            except (BrokenPipeError, OSError):
                log.warning("ffmpeg pipe closed for %s", self.path)
                self.proc = None
        elif self.cv:
            self.cv.write(frame)

    def close(self) -> None:
        if self.proc:
            self.proc.stdin.close()
            self.proc.wait(timeout=60)
        if self.cv:
            self.cv.release()


@dataclass
class _PendingClip:
    key: str
    sink: VideoSink
    remaining: int
    on_done: Optional[Callable[[str], None]] = None


@dataclass
class EvidenceRecorder:
    out_dir: Path
    fps: float  # effective (processed) frame rate
    pre_s: float = 3.0
    post_s: float = 3.0
    max_width: int = 960
    buffer: deque = field(init=False)
    pending: list[_PendingClip] = field(default_factory=list)

    def __post_init__(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.buffer = deque(maxlen=max(1, int(self.pre_s * self.fps)))

    def push(self, annotated: np.ndarray) -> None:
        """Add the current annotated frame; feeds any clips still being recorded."""
        small = _resize(annotated, self.max_width)
        ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            self.buffer.append(jpg)
        for clip in list(self.pending):
            clip.sink.write(small)
            clip.remaining -= 1
            if clip.remaining <= 0:
                self._finish(clip)

    def capture(self, key: str, snapshot: np.ndarray, on_clip_done: Optional[Callable[[str], None]] = None) -> tuple[str, str]:
        """Save a still now and start a clip (pre-buffer + post frames). Returns relative paths."""
        snap = _resize(snapshot, self.max_width)
        snap_path = self.out_dir / f"{key}.jpg"
        cv2.imwrite(str(snap_path), snap, [cv2.IMWRITE_JPEG_QUALITY, 88])
        clip_path = self.out_dir / f"{key}.mp4"
        h, w = snap.shape[:2]
        sink = VideoSink(clip_path, self.fps, (w, h))
        for jpg in self.buffer:
            sink.write(cv2.imdecode(jpg, cv2.IMREAD_COLOR))
        for _ in range(max(1, int(self.fps * 0.4))):  # brief freeze on the event frame
            sink.write(snap)
        self.pending.append(_PendingClip(key, sink, max(1, int(self.post_s * self.fps)), on_clip_done))
        return snap_path.name, clip_path.name

    def _finish(self, clip: _PendingClip) -> None:
        clip.sink.close()
        self.pending.remove(clip)
        if clip.on_done:
            clip.on_done(clip.key)

    def close(self) -> None:
        for clip in list(self.pending):
            self._finish(clip)
