"""Stereo calibration capture: keep still, varied board views seen by both cameras.

The two cameras are not synchronised, so a view is only taken while the board has been still in
both cameras for a moment; the two saved frames are then the newest of each camera (a few ms
apart) of a board that did not move. A view must also differ from those already taken (position,
size or tilt), so holding the board in one place does not fill the set with duplicates.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..config import ProcessorConfig
from ..session import Session
from .board import Checkerboard
from .calibrate import MIN_VIEWS, CalibrationError, StereoCalibration, calibrate, load_views

WINDOW = "LYNX SIGHT stereo calibration"


def pose_descriptor(corners: np.ndarray, board: Checkerboard, image_size) -> np.ndarray:
    """Where the board is (centre), how big (scale) and how it is tilted (edge-length ratios),
    all relative to the image, so distances between views are comparable."""
    w, h = image_size
    grid = corners.reshape(board.rows, board.cols, 2)
    centre = corners.mean(axis=0) / (w, h)
    top, bottom = (
        np.linalg.norm(grid[0, -1] - grid[0, 0]),
        np.linalg.norm(grid[-1, -1] - grid[-1, 0]),
    )
    left, right = (
        np.linalg.norm(grid[-1, 0] - grid[0, 0]),
        np.linalg.norm(grid[-1, -1] - grid[0, -1]),
    )
    scale = np.sqrt(max(top + bottom, 1e-6) * max(left + right, 1e-6) / 4) / w
    return np.array(
        [centre[0], centre[1], scale * 2, np.log(top / bottom) * 2, np.log(left / right) * 2]
    )


@dataclass
class ViewSelector:
    """Decides when to take a view. Feed it each camera's detections with `update`."""

    board: Checkerboard
    image_size: tuple[int, int]
    still_px: float = 1.5  # max corner movement between detections to count as still
    still_s: float = 0.6
    min_distance: float = 0.12  # between pose descriptors of a new and every taken view
    _last: dict = field(default_factory=dict)
    _still_since: dict = field(default_factory=dict)
    taken: list[np.ndarray] = field(default_factory=list)  # descriptors (cam_left)
    corners_taken: list[np.ndarray] = field(default_factory=list)

    def update(self, camera_id: str, t_ns: int, corners: np.ndarray | None) -> None:
        last = self._last.get(camera_id)
        if last is not None and t_ns <= last[0]:
            return  # already seen
        if corners is None:
            self._last[camera_id] = (t_ns, None)
            self._still_since.pop(camera_id, None)
            return
        moved = (
            float(np.max(np.linalg.norm(corners - last[1], axis=1)))
            if last is not None and last[1] is not None
            else float("inf")
        )
        if moved > self.still_px:
            self._still_since[camera_id] = t_ns
        self._last[camera_id] = (t_ns, corners)

    def still(self, camera_id: str, now_ns: int) -> bool:
        since = self._still_since.get(camera_id)
        last = self._last.get(camera_id)
        fresh = last is not None and last[1] is not None and now_ns - last[0] < 0.5e9
        return fresh and since is not None and (now_ns - since) / 1e9 >= self.still_s

    def novelty(self) -> float:
        last = self._last.get("cam_left")
        if last is None or last[1] is None:
            return 0.0
        d = pose_descriptor(last[1], self.board, self.image_size)
        if not self.taken:
            return float("inf")
        return float(min(np.linalg.norm(d - t) for t in self.taken))

    def ready(self, now_ns: int) -> bool:
        return (
            self.still("cam_left", now_ns)
            and self.still("cam_right", now_ns)
            and self.novelty() >= self.min_distance
        )

    def accept(self) -> None:
        corners = self._last["cam_left"][1]
        self.taken.append(pose_descriptor(corners, self.board, self.image_size))
        self.corners_taken.append(corners)
        for cid in list(self._still_since):
            self._still_since[cid] = None  # require a fresh still period


def _draw(frame_image, corners, board, ok: bool, width: int) -> np.ndarray:
    panel = cv2.cvtColor(frame_image, cv2.COLOR_GRAY2BGR)
    if corners is not None:
        cv2.drawChessboardCorners(panel, board.pattern_size, corners.reshape(-1, 1, 2), True)
    cv2.rectangle(
        panel,
        (0, 0),
        (panel.shape[1] - 1, panel.shape[0] - 1),
        (0, 200, 0) if ok else (0, 0, 200),
        6,
    )
    scale = width / panel.shape[1]
    return cv2.resize(panel, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def _coverage_map(corner_sets, image_size, width) -> np.ndarray:
    w, h = image_size
    scale = width / w
    canvas = np.zeros((round(h * scale), width, 3), np.uint8)
    for corners in corner_sets:
        hull = cv2.convexHull((corners * scale).astype(np.int32))
        overlay = canvas.copy()
        cv2.fillConvexPoly(overlay, hull, (0, 140, 0))
        canvas = cv2.addWeighted(canvas, 0.6, overlay, 0.4, 0)
    return canvas


def run_stereo_capture(
    session_factory,
    out_dir: Path,
    board: Checkerboard,
    target_views: int = 20,
    panel_width: int = 560,
    expected_baseline_mm: float | None = None,
    pitch_deg: float = 0.0,
) -> dict:
    """Live capture. `session_factory(processors)` builds the Session with the chessboard
    processor enabled. Keys: space = take a view now (both cameras must see the board),
    backspace = drop the last view, q / Esc = finish and solve."""
    session: Session = session_factory(
        {"chessboard": ProcessorConfig(True, 10.0, {"board": board.spec})}
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    session.start()
    selector: ViewSelector | None = None
    names: list[str] = []
    message = "hold the board still in view of both cameras"
    try:
        while True:
            frames = {cid: cam.slot.latest() for cid, cam in session.cameras.items()}
            results = {cid: session.board.latest(cid, "chessboard") for cid in session.cameras}
            if selector is None and frames.get("cam_left") is not None:
                f = frames["cam_left"]
                selector = ViewSelector(board, (f.width, f.height))
            now = time.monotonic_ns()
            corners = {}
            for cid, r in results.items():
                c = r.data.corners if r is not None and r.ok and r.data is not None else None
                if r is not None and now - r.frame.t_capture_ns > 0.5e9:
                    c = None
                corners[cid] = c
                if selector is not None and r is not None:
                    selector.update(cid, r.frame.t_capture_ns, c)
            take = False
            if selector is not None and selector.ready(now):
                take = True
            panels = []
            for cid in ("cam_left", "cam_right"):
                f = frames.get(cid)
                if f is None:
                    panels.append(np.zeros((round(panel_width * 0.625), panel_width, 3), np.uint8))
                    continue
                ok = selector is not None and selector.still(cid, now)
                panels.append(_draw(f.image, corners.get(cid), board, ok, panel_width))
            row = np.hstack(panels)
            if selector is not None:
                cov = _coverage_map(selector.corners_taken, selector.image_size, panel_width // 2)
                info = np.zeros((cov.shape[0], row.shape[1] - cov.shape[1], 3), np.uint8)
                lines = [
                    f"views {len(names)}/{target_views}  novelty {selector.novelty():.2f}",
                    "move: near/far, left/right/up/down, tilt +-30 deg; keep still to capture",
                    "space: take now   backspace: drop last   q: finish and solve",
                    message,
                ]
                for k, text in enumerate(lines):
                    cv2.putText(
                        info,
                        text,
                        (12, 26 + 26 * k),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (220, 220, 220),
                        1,
                        cv2.LINE_AA,
                    )
                row = np.vstack([row, np.hstack([cov, info])])
            cv2.imshow(WINDOW, row)
            key = cv2.waitKey(15) & 0xFF
            if key in (ord("q"), 27):
                break
            if (
                key == ord(" ")
                and corners.get("cam_left") is not None
                and corners.get("cam_right") is not None
            ):
                take = True
            if key == 8 and names:  # backspace
                name = names.pop()
                for cid in ("cam_left", "cam_right"):
                    (out_dir / f"{name}_{cid}.png").unlink(missing_ok=True)
                selector.taken.pop()
                selector.corners_taken.pop()
                message = f"dropped {name}"
            if (
                take
                and selector is not None
                and all(frames.get(c) is not None for c in ("cam_left", "cam_right"))
            ):
                fl, fr = (
                    session.cameras["cam_left"].slot.latest(),
                    session.cameras["cam_right"].slot.latest(),
                )
                name = f"view_{len(names):03d}_{int(time.time() * 1000) % 100000:05d}"
                cv2.imwrite(str(out_dir / f"{name}_cam_left.png"), fl.image)
                cv2.imwrite(str(out_dir / f"{name}_cam_right.png"), fr.image)
                skew = (fr.t_capture_ns - fl.t_capture_ns) / 1e6
                with (out_dir / "views.jsonl").open("a") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "name": name,
                                "skew_ms": round(skew, 2),
                                "t_left_ns": fl.t_capture_ns,
                                "t_right_ns": fr.t_capture_ns,
                            }
                        )
                        + "\n"
                    )
                names.append(name)
                selector.accept()
                message = f"took {name} (skew {skew:+.1f} ms)"
    finally:
        session.stop()
        cv2.destroyWindow(WINDOW)
    return solve_directory(out_dir, board, expected_baseline_mm, pitch_deg)


def solve_directory(
    directory: Path,
    board: Checkerboard,
    expected_baseline_mm: float | None = None,
    pitch_deg: float = 0.0,
    out: Path | None = None,
) -> dict:
    """Detects the corners in a capture directory, calibrates, writes stereo_calibration.json
    (or `out`) and returns the summary."""
    views, size = load_views(directory, board)
    detected = {
        "views": len(views),
        "cam_left": sum(v.left is not None for v in views),
        "cam_right": sum(v.right is not None for v in views),
    }
    try:
        cal = calibrate(views, board, size, pitch_deg)
    except CalibrationError as exc:
        return {"error": str(exc), "detected": detected, "min_views": MIN_VIEWS}
    cal.notes = {"capture_dir": str(directory), "detected": detected}
    path = out or Path(directory) / "stereo_calibration.json"
    cal.save(path)
    return {"saved": str(path), "detected": detected, **cal.summary(expected_baseline_mm)}


__all__ = ["ViewSelector", "run_stereo_capture", "solve_directory", "StereoCalibration"]
