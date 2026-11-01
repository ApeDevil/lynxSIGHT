"""Experiment configuration (YAML), following docs/architecture/shared-interface.md.

All lengths are millimetres and all angles degrees. Camera IDs are `cam_left` and `cam_right` as
seen by the user facing the cameras.
"""

from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

SCHEMA = "lynx-sight/experiment/v1"
CAMERA_IDS = ("cam_left", "cam_right")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ConfigError(ValueError):
    pass


@dataclass
class CaptureSettings:
    fourcc: str = "MJPG"
    width: int = 1280
    height: int = 800
    fps: float = 120  # the B0332 has no 60 fps mode at 1280x800; a 60 request gets 100
    # Driver buffers queued by OpenCV. With 1 the camera has nowhere to write while a frame
    # is being decoded, which capped the B0332 at ~68 of 120 fps (measured 2026-11-01).
    # 2 delivers the full rate; the app still only ever processes the newest frame.
    buffer_size: int = 2
    # V4L2 controls by normalised name (see `sight-diag list`), applied after opening,
    # e.g. {auto_exposure: 1, exposure_time_absolute: 100, gain: 0}.
    controls: dict[str, int] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        return f"{self.fourcc} {self.width}x{self.height}@{self.fps:g}"


@dataclass
class CameraConfig:
    camera_id: str
    # Stable device path, preferably /dev/v4l/by-path/... (see `sight-diag list`).
    # "synthetic" selects the built-in generator; a file or directory path replays a recording.
    device: str
    serial: str | None = None
    yaw_deg: float = 0.0  # 0 = parallel to rig Z; positive towards the rig centre
    pitch_deg: float = 0.0  # positive up
    # Overrides of the shared capture.controls for this camera only.
    controls: dict[str, int] = field(default_factory=dict)


@dataclass
class ProcessorConfig:
    enabled: bool = True
    max_hz: float | None = None  # None: as fast as frames arrive
    options: dict = field(default_factory=dict)


@dataclass
class ExperimentConfig:
    experiment_id: str
    cameras: dict[str, CameraConfig]
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    baseline_mm: float | None = 100.0
    user_distance_mm: float | None = 600.0
    processing: dict[str, ProcessorConfig] = field(default_factory=dict)
    output_dir: str = "experiments"
    notes: str = ""

    def capture_for(self, camera_id: str) -> CaptureSettings:
        settings = copy.deepcopy(self.capture)
        settings.controls.update(self.cameras[camera_id].controls)
        return settings

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "experiment_id": self.experiment_id,
            "notes": self.notes,
            "rig": {"baseline_mm": self.baseline_mm, "user_distance_mm": self.user_distance_mm},
            "cameras": {
                cid: {k: v for k, v in asdict(cam).items() if k != "camera_id"}
                for cid, cam in self.cameras.items()
            },
            "capture": asdict(self.capture),
            "processing": {name: asdict(p) for name, p in self.processing.items()},
            "output_dir": self.output_dir,
        }


DEFAULT_PROCESSING = {
    "quality": ProcessorConfig(True, 10.0),
    "face": ProcessorConfig(True, 30.0, {"input_width": 640, "score_threshold": 0.7}),
    "eyes": ProcessorConfig(True, None),
    # Reports itself unavailable (once) unless mediapipe and its model are installed.
    "landmarks": ProcessorConfig(True, 15.0),
}


def _number(value, name: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number, got {value!r}")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ConfigError(f"{name}={value} outside [{lo}, {hi}]")
    return value


def _controls(raw, name: str) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{name} must be a mapping of control name to integer")
    return {str(k): int(_number(v, f"{name}.{k}")) for k, v in raw.items()}


def from_dict(data: dict) -> ExperimentConfig:
    if not isinstance(data, dict):
        raise ConfigError("config must be a mapping")
    schema = data.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise ConfigError(f"unsupported schema {schema!r}, expected {SCHEMA!r}")
    exp_id = str(data.get("experiment_id", ""))
    if not _ID_RE.match(exp_id):
        raise ConfigError("experiment_id must be 1-64 chars of letters, digits, '.', '_' or '-'")

    raw_cams = data.get("cameras") or {}
    if not isinstance(raw_cams, dict) or not raw_cams:
        raise ConfigError("cameras must map camera ids (cam_left, cam_right) to settings")
    cameras = {}
    for cid, raw in raw_cams.items():
        if cid not in CAMERA_IDS:
            raise ConfigError(f"unknown camera id {cid!r}; use {', '.join(CAMERA_IDS)}")
        raw = raw or {}
        if not raw.get("device"):
            raise ConfigError(f"cameras.{cid}.device is required")
        cameras[cid] = CameraConfig(
            camera_id=cid,
            device=str(raw["device"]),
            serial=raw.get("serial"),
            yaw_deg=_number(raw.get("yaw_deg", 0.0), f"{cid}.yaw_deg", -25, 25),
            pitch_deg=_number(raw.get("pitch_deg", 0.0), f"{cid}.pitch_deg", -25, 25),
            controls=_controls(raw.get("controls"), f"cameras.{cid}.controls"),
        )

    raw_cap = data.get("capture") or {}
    fourcc = str(raw_cap.get("fourcc", "MJPG"))
    if len(fourcc) != 4:
        raise ConfigError("capture.fourcc must have 4 characters, e.g. MJPG or YUYV")
    capture = CaptureSettings(
        fourcc=fourcc,
        width=int(_number(raw_cap.get("width", 1280), "capture.width", 16, 8192)),
        height=int(_number(raw_cap.get("height", 800), "capture.height", 16, 8192)),
        fps=_number(raw_cap.get("fps", 120), "capture.fps", 1, 1000),
        buffer_size=int(_number(raw_cap.get("buffer_size", 2), "capture.buffer_size", 1, 32)),
        controls=_controls(raw_cap.get("controls"), "capture.controls"),
    )

    rig = data.get("rig") or {}
    processing = copy.deepcopy(DEFAULT_PROCESSING)
    for name, raw in (data.get("processing") or {}).items():
        if name not in processing:
            raise ConfigError(f"unknown processor {name!r}; known: {', '.join(processing)}")
        raw = raw or {}
        base = processing[name]
        max_hz = raw.get("max_hz", base.max_hz)
        processing[name] = ProcessorConfig(
            enabled=bool(raw.get("enabled", base.enabled)),
            max_hz=None
            if max_hz is None
            else _number(max_hz, f"processing.{name}.max_hz", 0.1, 1000),
            options={**base.options, **(raw.get("options") or {})},
        )

    def optional_mm(key: str) -> float | None:
        value = rig.get(key, data.get(key))
        return None if value is None else _number(value, f"rig.{key}", 0, 10_000)

    return ExperimentConfig(
        experiment_id=exp_id,
        cameras=cameras,
        capture=capture,
        baseline_mm=optional_mm("baseline_mm") if "baseline_mm" in rig else 100.0,
        user_distance_mm=optional_mm("user_distance_mm") if "user_distance_mm" in rig else 600.0,
        processing=processing,
        output_dir=str(data.get("output_dir", "experiments")),
        notes=str(data.get("notes", "") or ""),
    )


def load(path: str | Path) -> ExperimentConfig:
    try:
        data = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return from_dict(data)


def dump(config: ExperimentConfig) -> str:
    return yaml.safe_dump(config.to_dict(), sort_keys=False)


def quick_config(
    left: str | None,
    right: str | None,
    capture: CaptureSettings | None = None,
    experiment_id: str = "adhoc",
) -> ExperimentConfig:
    """Config built from command-line device arguments instead of a file."""
    cameras = {}
    for cid, device in zip(CAMERA_IDS, (left, right), strict=True):
        if device:
            cameras[cid] = CameraConfig(cid, device)
    if not cameras:
        raise ConfigError("no camera given")
    return ExperimentConfig(
        experiment_id=experiment_id,
        cameras=cameras,
        capture=capture or CaptureSettings(),
        processing=copy.deepcopy(DEFAULT_PROCESSING),
    )
