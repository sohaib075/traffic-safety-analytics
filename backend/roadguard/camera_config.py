"""Camera / scene configuration.

All image geometry is given in *normalized* coordinates (0..1 of frame width/height), so a
config keeps working when the same camera is recorded at a different resolution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from . import settings

Point = tuple[float, float]

VEHICLE_CLASSES = ("car", "motorcycle", "bus", "truck", "bicycle")
PERSON_CLASS = "person"


class LatLng(BaseModel):
    lat: float
    lng: float


class Calibration(BaseModel):
    """Maps image points to a ground plane in metres.

    Either give four (or more) image↔world point pairs for a homography, or an approximate
    scene width in metres (uniform scale — cruder, but fine for relative comparisons).
    """

    image_points: Optional[list[Point]] = None  # normalized image coords
    world_points: Optional[list[Point]] = None  # metres
    approx_scene_width_m: float = 40.0
    # Estimate the uniform scale from the median width of detected cars (≈1.8 m) in a quick
    # pre-pass over the video. Used for arbitrary uploads without a site calibration.
    auto_scale: bool = False

    @property
    def has_homography(self) -> bool:
        return bool(self.image_points and self.world_points and len(self.image_points) >= 4)


class Zone(BaseModel):
    id: str
    name: str
    type: Literal["intersection", "crosswalk", "no_stopping", "road", "parking"] = "road"
    polygon: list[Point]
    location: Optional[LatLng] = None


class Lane(BaseModel):
    id: str
    name: str
    polygon: list[Point]
    direction: Point  # expected direction of travel in image space, e.g. [1, 0] = left→right
    zone_id: Optional[str] = None


class Signal(BaseModel):
    id: str
    name: str = "Signal"
    # roi:       classify red/green from the colour of a lamp region in the frame
    # schedule:  fixed cycle (seconds from video start)
    # always_red / always_green: useful for testing and for feeds without a visible signal
    mode: Literal["roi", "schedule", "always_red", "always_green"] = "schedule"
    roi: Optional[tuple[float, float, float, float]] = None  # x1,y1,x2,y2 normalized
    cycle_s: float = 60.0
    red_s: float = 30.0
    offset_s: float = 0.0


class StopLine(BaseModel):
    id: str
    name: str = "Stop line"
    line: tuple[Point, Point]
    crossing_direction: Point  # direction of travel that counts as "entering the junction"
    signal_id: str
    zone_id: Optional[str] = None


class CountingLine(BaseModel):
    id: str
    name: str = "Count line"
    line: tuple[Point, Point]


class NearMissRule(BaseModel):
    enabled: bool = True
    horizon_s: float = 2.0  # look-ahead for closest-point-of-approach
    ttc_threshold_s: float = 1.5
    margin_m: float = 0.8  # extra clearance added to the two objects' radii
    min_speed_mps: float = 2.0  # at least one party must be moving this fast
    min_closing_mps: float = 2.0  # the gap must be shrinking at least this fast
    confirm_frames: int = 2  # condition must hold on consecutive processed frames
    cooldown_s: float = 5.0
    zones: list[str] = []  # restrict to these zone ids (empty = whole frame)


class PedConflictRule(BaseModel):
    enabled: bool = True
    horizon_s: float = 2.5
    ttc_threshold_s: float = 2.0
    margin_m: float = 1.0
    min_vehicle_speed_mps: float = 2.0
    min_closing_mps: float = 1.5
    confirm_frames: int = 2
    cooldown_s: float = 5.0
    zones: list[str] = []  # e.g. crosswalks; empty = whole frame


class WrongWayRule(BaseModel):
    enabled: bool = True
    window_s: float = 1.5
    min_displacement_m: float = 3.0
    cos_threshold: float = -0.5  # cos(angle) between motion and lane direction
    confirm_windows: int = 3


class RedLightRule(BaseModel):
    enabled: bool = True


class IllegalStopRule(BaseModel):
    enabled: bool = True
    speed_threshold_mps: float = 0.6
    dwell_s: float = 20.0


class CongestionRule(BaseModel):
    enabled: bool = True
    min_vehicles: int = 8
    max_avg_speed_mps: float = 2.0
    sustain_s: float = 30.0
    cooldown_s: float = 120.0


class HelmetRule(BaseModel):
    enabled: bool = False
    # Path to a YOLO model with classes "helmet" / "no_helmet": a classifier on motorcycle crops
    # (backend/training) or a head detector. COCO has no such class, so it stays off until set.
    model: Optional[str] = None
    no_helmet_classes: list[str] = ["no_helmet", "no-helmet", "without_helmet", "head"]
    helmet_classes: list[str] = ["helmet", "with_helmet"]
    imgsz: int = 224  # classifier input size (match training)
    check_every_s: float = 0.2  # how often each motorcycle track is classified
    min_crop_height: int = 48  # px; smaller motorcycles are too far away to judge
    # Classifier mode: decide on the MEAN P(no_helmet) over a track's checks (how the model was
    # evaluated offline). Raise threshold for fewer false alarms, lower it to catch more.
    min_checks: int = 4
    threshold: float = 0.5
    early_threshold: float = 0.6  # incidents before confirm_checks need this mean
    confirm_checks: int = 8
    skip_edge_crops: bool = True  # ignore motorcycles cut off by the frame border (unreliable)
    min_votes: int = 3  # head-detector mode only


class Rules(BaseModel):
    near_miss: NearMissRule = NearMissRule()
    ped_conflict: PedConflictRule = PedConflictRule()
    wrong_way: WrongWayRule = WrongWayRule()
    red_light: RedLightRule = RedLightRule()
    illegal_stop: IllegalStopRule = IllegalStopRule()
    congestion: CongestionRule = CongestionRule()
    helmet: HelmetRule = HelmetRule()


class Privacy(BaseModel):
    blur_heads: bool = True  # blur the head region of detected people in evidence + stream
    plate_model: Optional[str] = None  # optional licence-plate detector to blur plates


class EvidenceSettings(BaseModel):
    pre_s: float = 3.0
    post_s: float = 3.0
    max_width: int = 960


class CameraConfig(BaseModel):
    id: str
    name: str
    location: Optional[LatLng] = None
    classes: list[str] = Field(default_factory=lambda: [PERSON_CLASS, *VEHICLE_CLASSES])
    # Per-camera detector / tracker overrides (paths relative to backend/). Busy two-wheeler
    # traffic at low frame rates benefits from a larger detector and a looser tracker.
    model: Optional[str] = None  # default: ROADGUARD_MODEL (yolov8n.pt)
    tracker: str = "bytetrack.yaml"  # or e.g. config/trackers/roadguard_bytetrack.yaml
    conf_threshold: float = 0.3
    frame_stride: int = 1  # process every Nth frame (CPU-friendly)
    imgsz: int = 640
    calibration: Calibration = Calibration()
    zones: list[Zone] = []
    lanes: list[Lane] = []
    signals: list[Signal] = []
    stop_lines: list[StopLine] = []
    counting_lines: list[CountingLine] = []
    rules: Rules = Rules()
    privacy: Privacy = Privacy()
    evidence: EvidenceSettings = EvidenceSettings()

    def zone(self, zone_id: Optional[str]) -> Optional[Zone]:
        return next((z for z in self.zones if z.id == zone_id), None)


def load_camera_config(path: str | Path) -> CameraConfig:
    with open(path, "r", encoding="utf-8") as f:
        return CameraConfig.model_validate(yaml.safe_load(f))


def camera_config_path(camera_id: str) -> Path:
    return settings.CAMERA_CONFIG_DIR / f"{camera_id}.yaml"


def save_camera_config(cfg: CameraConfig) -> Path:
    settings.ensure_dirs()
    path = camera_config_path(cfg.id)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(mode="json", exclude_none=True), f, sort_keys=False)
    return path


def list_camera_configs() -> list[CameraConfig]:
    settings.ensure_dirs()
    return [load_camera_config(p) for p in sorted(settings.CAMERA_CONFIG_DIR.glob("*.yaml"))]
