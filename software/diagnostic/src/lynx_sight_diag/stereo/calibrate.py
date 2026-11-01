"""Checkerboard calibration: intrinsics of each camera, then the extrinsics between them.

Each camera is calibrated alone on every view where it saw the board (pinhole + k1, k2, p1, p2;
k3 is fixed at 0 because the B0332 lens is sold as low-distortion and k3 overfits with few
views). Views whose own reprojection error is far above the rest are dropped once and the
camera recalibrated. The extrinsics are then solved with the intrinsics fixed, on the views where
both cameras saw the board.

The result is saved as ``lynx-sight/stereo-calibration/v1`` JSON and loaded as a `StereoRig`.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .board import Checkerboard, find_corners
from .rig import StereoRig

SCHEMA = "lynx-sight/stereo-calibration/v1"
INTRINSIC_FLAGS = cv2.CALIB_FIX_K3
MIN_VIEWS = 6  # per camera and for the pair; 15-25 varied views are recommended


class CalibrationError(ValueError):
    pass


@dataclass
class View:
    """One captured pose of the board: corners per camera (None where not detected)."""

    name: str
    left: np.ndarray | None
    right: np.ndarray | None
    skew_ms: float | None = None  # capture-time difference of the two images


@dataclass
class CameraResult:
    K: np.ndarray
    dist: np.ndarray
    rms_px: float
    view_errors_px: dict[str, float]
    rejected: list[str] = field(default_factory=list)
    coverage: float = 0.0  # fraction of a 8x5 image grid that holds at least one corner


def _view_errors(obj, img, rvecs, tvecs, K, dist) -> list[float]:
    errs = []
    for o, i, r, t in zip(obj, img, rvecs, tvecs, strict=True):
        proj, _ = cv2.projectPoints(o, r, t, K, dist)
        errs.append(
            float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - i.reshape(-1, 2)) ** 2, 1))))
        )
    return errs


def coverage(corner_sets: list[np.ndarray], image_size: tuple[int, int], grid=(8, 5)) -> float:
    w, h = image_size
    cells = set()
    for corners in corner_sets:
        for x, y in corners.reshape(-1, 2):
            cells.add(
                (min(grid[0] - 1, int(x / w * grid[0])), min(grid[1] - 1, int(y / h * grid[1])))
            )
    return len(cells) / (grid[0] * grid[1])


def calibrate_camera(
    names: list[str],
    corner_sets: list[np.ndarray],
    board: Checkerboard,
    image_size: tuple[int, int],
    reject_factor: float = 3.0,
) -> CameraResult:
    if len(corner_sets) < MIN_VIEWS:
        raise CalibrationError(f"need at least {MIN_VIEWS} views, got {len(corner_sets)}")
    obj = board.object_points()

    def run(sel):
        o = [obj] * len(sel)
        i = [corner_sets[k].reshape(-1, 1, 2).astype(np.float32) for k in sel]
        rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
            o, i, image_size, None, None, flags=INTRINSIC_FLAGS
        )
        return rms, K, dist, _view_errors(o, i, rvecs, tvecs, K, dist)

    keep = list(range(len(corner_sets)))
    rms, K, dist, errs = run(keep)
    limit = max(reject_factor * float(np.median(errs)), 0.5)
    rejected = [names[k] for k, e in zip(keep, errs, strict=True) if e > limit]
    if rejected and len(keep) - len(rejected) >= MIN_VIEWS:
        keep = [k for k, e in zip(keep, errs, strict=True) if e <= limit]
        rms, K, dist, errs = run(keep)
    else:
        rejected = []
    return CameraResult(
        K,
        dist.ravel(),
        float(rms),
        {names[k]: round(e, 3) for k, e in zip(keep, errs, strict=True)},
        rejected,
        coverage([corner_sets[k] for k in keep], image_size),
    )


@dataclass
class StereoCalibration:
    board: Checkerboard
    image_size: tuple[int, int]
    left: CameraResult
    right: CameraResult
    R: np.ndarray  # x_right = R x_left + T
    T: np.ndarray  # mm
    stereo_rms_px: float
    epipolar_px: float  # median distance of right corners from their epipolar lines
    pair_views: list[str]
    pitch_deg: float = 0.0
    created: str = ""
    notes: dict = field(default_factory=dict)

    @property
    def baseline_mm(self) -> float:
        return float(np.linalg.norm(self.T))

    @property
    def relative_rotation_deg(self) -> float:
        return math.degrees(float(np.linalg.norm(cv2.Rodrigues(self.R)[0])))

    def rig(self) -> StereoRig:
        return StereoRig.from_extrinsics(
            self.image_size,
            self.left.K,
            self.left.dist,
            self.right.K,
            self.right.dist,
            self.R,
            self.T,
            self.pitch_deg,
        )

    def warnings(self, expected_baseline_mm: float | None = None) -> list[str]:
        out = []
        cx = (-self.R.T @ self.T)[0]
        if cx > 0:
            out.append(
                "cam_right appears to the LEFT of cam_left: the cameras are swapped in the config"
            )
        for cid, cam in (("cam_left", self.left), ("cam_right", self.right)):
            if cam.rms_px > 1.0:
                out.append(
                    f"{cid}: reprojection RMS {cam.rms_px:.2f} px > 1 px (blur, bent board?)"
                )
            if cam.coverage < 0.5:
                out.append(
                    f"{cid}: corners cover only {cam.coverage:.0%} of the image; "
                    "hold the board near the edges and corners too"
                )
        if self.epipolar_px > 1.0:
            out.append(
                f"epipolar error {self.epipolar_px:.2f} px > 1 px: board moved between "
                "the two exposures, or the intrinsics are poor"
            )
        if expected_baseline_mm and abs(self.baseline_mm - expected_baseline_mm) > 5:
            out.append(
                f"baseline {self.baseline_mm:.1f} mm differs from the configured "
                f"{expected_baseline_mm:g} mm by more than 5 mm; check the square size"
            )
        if len(self.pair_views) < 10:
            out.append(f"only {len(self.pair_views)} views seen by both cameras; 15-25 recommended")
        return out

    def summary(self, expected_baseline_mm: float | None = None) -> dict:
        return {
            "board": self.board.spec,
            "image_size": list(self.image_size),
            "views": {
                "cam_left": len(self.left.view_errors_px),
                "cam_right": len(self.right.view_errors_px),
                "both": len(self.pair_views),
            },
            "rms_px": {
                "cam_left": round(self.left.rms_px, 3),
                "cam_right": round(self.right.rms_px, 3),
                "stereo": round(self.stereo_rms_px, 3),
            },
            "focal_px": {
                "cam_left": [
                    round(float(self.left.K[0, 0]), 1),
                    round(float(self.left.K[1, 1]), 1),
                ],
                "cam_right": [
                    round(float(self.right.K[0, 0]), 1),
                    round(float(self.right.K[1, 1]), 1),
                ],
            },
            "hfov_deg": {
                cid: round(2 * math.degrees(math.atan(self.image_size[0] / 2 / cam.K[0, 0])), 1)
                for cid, cam in (("cam_left", self.left), ("cam_right", self.right))
            },
            "baseline_mm": round(self.baseline_mm, 2),
            "relative_rotation_deg": round(self.relative_rotation_deg, 2),
            "epipolar_px": round(self.epipolar_px, 3),
            "coverage": {
                "cam_left": round(self.left.coverage, 2),
                "cam_right": round(self.right.coverage, 2),
            },
            "rejected_views": {"cam_left": self.left.rejected, "cam_right": self.right.rejected},
            "warnings": self.warnings(expected_baseline_mm),
        }

    # --- persistence ---------------------------------------------------------------------------

    def to_dict(self) -> dict:
        def cam(c: CameraResult) -> dict:
            return {
                "K": c.K.tolist(),
                "dist": c.dist.tolist(),
                "rms_px": c.rms_px,
                "view_errors_px": c.view_errors_px,
                "rejected": c.rejected,
                "coverage": c.coverage,
            }

        return {
            "schema": SCHEMA,
            "created": self.created,
            "board": self.board.to_dict(),
            "image_size": list(self.image_size),
            "distortion_model": "opencv k1 k2 p1 p2 k3 (k3 fixed at 0)",
            "cameras": {"cam_left": cam(self.left), "cam_right": cam(self.right)},
            "stereo": {
                "convention": "x_cam_right = R @ x_cam_left + T, mm",
                "R": self.R.tolist(),
                "T_mm": self.T.ravel().tolist(),
                "rms_px": self.stereo_rms_px,
                "epipolar_px": self.epipolar_px,
                "baseline_mm": self.baseline_mm,
                "views": self.pair_views,
            },
            "rig": {"pitch_deg": self.pitch_deg},
            "provenance": "measured: checkerboard calibration",
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StereoCalibration:
        if data.get("schema") != SCHEMA:
            raise CalibrationError(f"not a {SCHEMA} file (schema {data.get('schema')!r})")

        def cam(d: dict) -> CameraResult:
            return CameraResult(
                np.array(d["K"], float),
                np.array(d["dist"], float),
                float(d["rms_px"]),
                dict(d.get("view_errors_px", {})),
                list(d.get("rejected", [])),
                float(d.get("coverage", 0.0)),
            )

        st = data["stereo"]
        return cls(
            Checkerboard.from_dict(data["board"]),
            tuple(data["image_size"]),
            cam(data["cameras"]["cam_left"]),
            cam(data["cameras"]["cam_right"]),
            np.array(st["R"], float),
            np.array(st["T_mm"], float),
            float(st["rms_px"]),
            float(st["epipolar_px"]),
            list(st.get("views", [])),
            float(data.get("rig", {}).get("pitch_deg", 0.0)),
            data.get("created", ""),
            data.get("notes", {}),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> StereoCalibration:
        return cls.from_dict(json.loads(Path(path).read_text()))


def load_rig(path: str | Path) -> StereoRig:
    return StereoCalibration.load(path).rig()


def epipolar_error(F: np.ndarray, left: list[np.ndarray], right: list[np.ndarray]) -> float:
    """Median distance (px) of right corners from the epipolar lines of the left ones. Uses the
    distorted pixels, so it also contains residual distortion; < 0.5 px is good."""
    dists = []
    for pl, pr in zip(left, right, strict=True):
        lines = cv2.computeCorrespondEpilines(pl.reshape(-1, 1, 2), 1, F).reshape(-1, 3)
        dists.append(np.abs(np.sum(lines[:, :2] * pr.reshape(-1, 2), 1) + lines[:, 2]))
    return float(np.median(np.concatenate(dists))) if dists else float("nan")


def calibrate(
    views: list[View], board: Checkerboard, image_size: tuple[int, int], pitch_deg: float = 0.0
) -> StereoCalibration:
    cams = {}
    for side in ("left", "right"):
        pairs = [(v.name, getattr(v, side)) for v in views if getattr(v, side) is not None]
        cams[side] = calibrate_camera(
            [n for n, _ in pairs], [c for _, c in pairs], board, image_size
        )
    rejected = set(cams["left"].rejected) | set(cams["right"].rejected)
    both = [
        v for v in views if v.left is not None and v.right is not None and v.name not in rejected
    ]
    if len(both) < MIN_VIEWS:
        raise CalibrationError(
            f"need at least {MIN_VIEWS} views seen by both cameras, got {len(both)}"
        )
    obj = [board.object_points()] * len(both)
    il = [v.left.reshape(-1, 1, 2).astype(np.float32) for v in both]
    ir = [v.right.reshape(-1, 1, 2).astype(np.float32) for v in both]
    L, Rc = cams["left"], cams["right"]
    rms, *_, R, T, _E, F = cv2.stereoCalibrate(
        obj, il, ir, L.K, L.dist, Rc.K, Rc.dist, image_size, flags=cv2.CALIB_FIX_INTRINSIC
    )
    return StereoCalibration(
        board,
        tuple(image_size),
        L,
        Rc,
        np.asarray(R, float),
        np.asarray(T, float).ravel(),
        float(rms),
        epipolar_error(F, il, ir),
        [v.name for v in both],
        pitch_deg,
        time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )


# --- capture directories -----------------------------------------------------------------------


def load_views(directory: Path, board: Checkerboard) -> tuple[list[View], tuple[int, int]]:
    """Reads `<name>_cam_left.png` / `<name>_cam_right.png` pairs written by the capture tool
    and detects the corners again (so a capture can be re-solved with other settings)."""
    directory = Path(directory)
    names = sorted({p.name.rsplit("_cam_", 1)[0] for p in directory.glob("*_cam_*.png")})
    meta = {}
    meta_path = directory / "views.jsonl"
    if meta_path.exists():
        for line in meta_path.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                meta[entry["name"]] = entry
    views, size = [], None
    for name in names:
        corners = {}
        for cid in ("cam_left", "cam_right"):
            path = directory / f"{name}_{cid}.png"
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.exists() else None
            if image is None:
                corners[cid] = None
                continue
            image_size = (image.shape[1], image.shape[0])
            if size is None:
                size = image_size
            elif size != image_size:
                raise CalibrationError(f"{path.name}: {image_size} differs from {size}")
            corners[cid] = find_corners(image, board)
        views.append(
            View(name, corners["cam_left"], corners["cam_right"], meta.get(name, {}).get("skew_ms"))
        )
    if size is None:
        raise CalibrationError(f"no *_cam_left.png / *_cam_right.png images in {directory}")
    return views, size
