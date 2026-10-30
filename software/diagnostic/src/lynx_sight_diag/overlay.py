"""Renders the diagnostic view: camera panels with overlays plus magnified eye regions.

Pure rendering (numpy in, numpy out), so it is testable headless and the GUI loop only shows
the returned canvas.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .capture import CaptureStatus, State
from .processing import Result, RunnerStats
from .processing.eyes import Eyes
from .processing.face import Faces
from .processing.landmarks import Landmarks
from .processing.quality import Quality

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN, YELLOW, RED, CYAN, WHITE, GREY = (
    (80, 220, 80),
    (0, 220, 255),
    (60, 60, 255),
    (255, 220, 0),
    (255, 255, 255),
    (150, 150, 150),
)
IRIS = (255, 0, 255)  # MediaPipe iris centres
STATE_COLOUR = {
    State.RUNNING: GREEN,
    State.OPENING: YELLOW,
    State.ERROR: RED,
    State.STOPPED: GREY,
    State.ENDED: GREY,
}


def _fmt(value: float | None, spec: str = ".1f", unit: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:{spec}}{unit}"


def _text(img, text: str, org, colour=WHITE, scale=0.5, thickness=1) -> None:
    """Text on a dark box, readable on any image content."""
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thickness)
    x, y = org
    x0, y0, x1, y1 = (
        max(0, x - 2),
        max(0, y - th - 3),
        min(img.shape[1], x + tw + 2),
        min(img.shape[0], y + base + 1),
    )
    if x1 > x0 and y1 > y0:
        img[y0:y1, x0:x1] = (img[y0:y1, x0:x1] * 0.35).astype(img.dtype)
    cv2.putText(img, text, org, FONT, scale, colour, thickness, cv2.LINE_AA)


def _confidence_colour(c: float) -> tuple[int, int, int]:
    return GREEN if c >= 0.6 else YELLOW if c >= 0.3 else RED


def draw_panel(
    image: np.ndarray | None,
    status: CaptureStatus,
    results: dict[str, Result],
    stats: dict[str, RunnerStats],
    width: int,
    controls: dict[str, int | None],
    selected: bool,
    show_overlays: bool = True,
) -> np.ndarray:
    """One camera panel scaled to `width` px."""
    if image is None:
        height = round(width * 800 / 1280)
        panel = np.full((height, width, 3), 32, np.uint8)
    else:
        scale_h = round(image.shape[0] * width / image.shape[1])
        panel = cv2.cvtColor(
            cv2.resize(image, (width, scale_h), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR
        )
    s = panel.shape[1] / image.shape[1] if image is not None else 1.0

    if show_overlays and image is not None:
        face = results.get("face")
        if face and isinstance(face.data, Faces):
            for f in face.data.faces:
                x, y, w, h = (v * s for v in f.box)
                cv2.rectangle(
                    panel,
                    (int(x), int(y)),
                    (int(x + w), int(y + h)),
                    _confidence_colour(f.score),
                    2,
                )
                _text(
                    panel,
                    f"face {f.score:.2f}",
                    (int(x), max(12, int(y) - 6)),
                    _confidence_colour(f.score),
                )
                for px, py in f.landmarks.values():
                    cv2.circle(panel, (int(px * s), int(py * s)), 3, CYAN, -1)
        lm = results.get("landmarks")
        if lm and isinstance(lm.data, Landmarks):
            for px, py in lm.data.points[::3]:
                cv2.circle(panel, (int(px * s), int(py * s)), 1, (200, 120, 255), -1)
            for px, py in lm.data.iris_centres:
                cv2.drawMarker(
                    panel, (int(px * s), int(py * s)), IRIS, cv2.MARKER_TILTED_CROSS, 8, 1
                )
            if lm.data.head_pose_deg:
                yaw, pitch, roll = lm.data.head_pose_deg
                _text(
                    panel,
                    f"pose~ yaw {yaw:+.0f} pitch {pitch:+.0f} roll {roll:+.0f} (uncal.)",
                    (8, panel.shape[0] - 34),
                    (200, 120, 255),
                )
        eyes = results.get("eyes")
        if eyes and isinstance(eyes.data, Eyes):
            for region in eyes.data.regions:
                x, y, w, h = (v * s for v in region.roi)
                cv2.rectangle(panel, (int(x), int(y)), (int(x + w), int(y + h)), CYAN, 1)
                if region.pupil_xy and region.pupil:
                    px, py = region.pupil_xy
                    cv2.circle(
                        panel,
                        (int(px * s), int(py * s)),
                        max(2, int(region.pupil.radius * s)),
                        _confidence_colour(region.pupil.confidence),
                        1,
                    )

    # Header: identity, state, mode and timing.
    colour = STATE_COLOUR.get(status.state, WHITE)
    title = (
        f"{status.camera_id}{' *' if selected else ''}  [{status.state.value}]  {status.negotiated}"
    )
    _text(panel, title, (8, 20), colour, 0.55)
    _text(panel, status.description[-60:], (8, 40), GREY, 0.4)
    timing = (
        f"fps {_fmt(status.fps)}  frames {status.frames}  drops~ {status.est_dropped}  "
        f"dt p50/p95 {_fmt(status.interval_p50_ms)}/{_fmt(status.interval_p95_ms)} ms  "
        f"drv-lat {_fmt(status.driver_latency_ms)} ms"
    )
    _text(panel, timing, (8, 60), WHITE, 0.45)
    ctl = "  ".join(
        f"{k.replace('exposure_time_absolute', 'exposure')}={v}"
        for k, v in controls.items()
        if v is not None
    )
    if ctl:
        _text(panel, ctl, (8, 80), WHITE, 0.45)
    if status.error:
        _text(panel, status.error[:90], (8, 100), RED, 0.45)

    # Processing summary lines at the bottom.
    y = panel.shape[0] - 10
    lines = []
    quality = results.get("quality")
    if quality and isinstance(quality.data, Quality):
        q = quality.data
        lines.append(
            (
                f"level {q.mean:.0f}  p1/p99 {q.p01:.0f}/{q.p99:.0f}  sat {q.saturated_pct:.1f}%  "
                f"sharp {q.sharpness:.0f}",
                WHITE,
            )
        )
    for name, st in stats.items():
        if st.unavailable:
            lines.append((f"{name}: {st.unavailable}", YELLOW))
            continue
        lat = st.latency_summary()
        err = f"  err {st.errors}" if st.errors else ""
        lines.append(
            (
                f"{name}: lat p50 {_fmt(lat.p50)} ms  cpu {_fmt(st.compute_summary().p50)} ms  "
                f"skip {st.skipped}{err}",
                RED if st.consecutive_errors else GREY,
            )
        )
    for text, col in reversed(lines):
        _text(panel, text, (8, y), col, 0.42)
        y -= 18
    return panel


def eye_tiles(
    image: np.ndarray | None,
    eyes: Result | None,
    iris_centres: list[tuple[float, float]] | None = None,
    tile: int = 160,
) -> list[np.ndarray]:
    """Magnified eye regions, `tile` px high, with the pupil marked. Nearest-neighbour scaling
    keeps the real pixels visible, which shows how many pixels the pupil actually spans.
    `iris_centres` (MediaPipe, same frame) are drawn as magenta crosses for comparison."""
    tiles = []
    if image is None or eyes is None or not isinstance(eyes.data, Eyes):
        return tiles
    for region in eyes.data.regions:
        x, y, w, h = region.roi
        crop = image[y : y + h, x : x + w]
        if crop.size == 0:
            continue
        zoom = tile / h
        size = (max(1, round(w * zoom)), tile)
        big = cv2.cvtColor(
            cv2.resize(crop, size, interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR
        )
        p = region.pupil
        if p:
            colour = _confidence_colour(p.confidence)
            centre = (int(p.x * zoom), int(p.y * zoom))
            cv2.circle(big, centre, max(2, int(p.radius * zoom)), colour, 1)
            cv2.drawMarker(big, centre, colour, cv2.MARKER_CROSS, 10, 1)
            _text(big, f"{p.confidence:.2f}", (4, tile - 6), colour, 0.4)
        else:
            _text(big, "no pupil", (4, tile - 6), RED, 0.4)
        for ix, iy in iris_centres or []:
            if x <= ix < x + w and y <= iy < y + h:
                mark = (int((ix - x) * zoom), int((iy - y) * zoom))
                cv2.drawMarker(big, mark, IRIS, cv2.MARKER_TILTED_CROSS, 12, 1)
        _text(big, f"{eyes.camera_id} {region.label} x{zoom:.1f}", (4, 14), WHITE, 0.4)
        tiles.append(big)
    return tiles


HELP = (
    "q quit | space pause | r reconnect | s snapshot | tab camera | [ ] exposure | - = gain | "
    "a auto-exp | o overlays | R record | 0-9 phase"
)


def compose(panels: list[np.ndarray], tiles: list[np.ndarray], footer: str) -> np.ndarray:
    height = max(p.shape[0] for p in panels)
    row = np.hstack(
        [cv2.copyMakeBorder(p, 0, height - p.shape[0], 0, 0, cv2.BORDER_CONSTANT) for p in panels]
    )
    tile = tiles[0].shape[0] if tiles else 160
    strip = np.full((tile, row.shape[1], 3), 24, np.uint8)
    x = 0
    for t in tiles:
        if x + t.shape[1] > strip.shape[1]:
            break
        strip[:, x : x + t.shape[1]] = t
        x += t.shape[1] + 4
    if not tiles:
        _text(strip, "eye regions appear here when a face is detected", (8, tile // 2), GREY, 0.5)
    bar = np.full((44, row.shape[1], 3), 16, np.uint8)
    _text(bar, footer[:200], (8, 16), WHITE, 0.45)
    _text(bar, HELP, (8, 36), GREY, 0.42)
    return np.vstack([row, strip, bar])
