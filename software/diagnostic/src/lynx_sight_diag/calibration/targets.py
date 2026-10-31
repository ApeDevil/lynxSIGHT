"""Target plans: where stationary targets appear and which paths pursuit targets follow.

The engine is the only place where target positions and trajectories are computed; the UI
draws what it is given and reports what it drew. Positions are normalized display coordinates
(0..1, origin top-left). Paths are sampled densely enough (`PATH_STEP_MS`) for the presenter
to interpolate linearly, and parameterised by arc length *on screen* (aspect-corrected) so the
target moves at a constant visible speed.
"""

from __future__ import annotations

import math

import numpy as np

from . import grid_targets

PATH_STEP_MS = 1000.0 / 120.0


def stationary_points(layout: dict) -> list[tuple[float, float]]:
    kind = layout["layout"]
    if kind == "centre_edges_corners":
        m = layout["margin"]
        centre = [(0.5, 0.5)]
        edges = [(0.5, m), (1 - m, 0.5), (0.5, 1 - m), (m, 0.5)]
        corners = [(m, m), (1 - m, m), (1 - m, 1 - m), (m, 1 - m)]
        return centre + edges + corners
    if kind == "grid":
        return _grid(layout["cols"], layout["rows"], layout["margin"])
    if kind == "validation_offset_grid":
        # Midpoints between the fit grid's points: never a fit position.
        cols, rows, m = layout["cols"], layout["rows"], layout["margin"]
        xs = _midpoints(cols, m)
        ys = _midpoints(rows, m)
        return [(x, y) for y in ys for x in xs]
    if kind == "points":
        return [(p["x"], p["y"]) for p in layout["points"]]
    raise ValueError(f"unknown layout {kind!r}")


def _grid(cols: int, rows: int, margin: float) -> list[tuple[float, float]]:
    scale = 1_000_000  # reuse the pixel grid helper at high resolution
    return [(x / scale, y / scale) for x, y in grid_targets(cols, rows, scale, scale, margin)]


def _midpoints(n: int, margin: float) -> list[float]:
    if n < 2:
        return [0.5]
    edges = np.linspace(margin, 1 - margin, n)
    return [float(v) for v in (edges[:-1] + edges[1:]) / 2]


def stationary_plan(plan_id: str, request: dict) -> dict:
    points = stationary_points(request["layout"])
    for x, y in points:
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"target ({x}, {y}) is off the display")
    per_target = request["settle_ms"] + request["dwell_ms"]
    return {
        "plan_id": plan_id,
        "purpose": request["purpose"],
        "duration_ms": float(per_target * len(points)),
        "body": {
            "method": "stationary",
            "targets": [
                {"index": i, "position": {"x": x, "y": y}} for i, (x, y) in enumerate(points)
            ],
            "settle_ms": request["settle_ms"],
            "dwell_ms": request["dwell_ms"],
        },
    }


def trajectory_polyline(trajectory: dict, n: int = 2000) -> np.ndarray:
    """The trajectory as a dense polyline of normalized points (N, 2)."""
    kind = trajectory["trajectory"]
    m = trajectory["margin"]
    if kind == "spiral":
        turns = trajectory["turns"]
        t = np.linspace(0, 1, n)
        angle = 2 * math.pi * turns * t
        # Reach the margin on both axes: the spiral is an ellipse in normalized units, which
        # looks like a stretched circle on a wide display.
        r = t * (0.5 - m)
        return np.column_stack([0.5 + r * np.cos(angle), 0.5 + r * np.sin(angle)])
    if kind == "perimeter":
        lo, hi = m, 1 - m
        corners = [(lo, lo), (hi, lo), (hi, hi), (lo, hi), (lo, lo)]
        return np.array(corners, float)
    if kind == "sweeps":
        lo, hi = m, 1 - m
        pts: list[tuple[float, float]] = []
        for i, y in enumerate(np.linspace(lo, hi, max(trajectory["rows"], 1))):
            row = [(lo, y), (hi, y)] if i % 2 == 0 else [(hi, y), (lo, y)]
            pts.extend(row)
        for i, x in enumerate(np.linspace(lo, hi, max(trajectory["cols"], 1))):
            col = [(x, lo), (x, hi)] if i % 2 == 0 else [(x, hi), (x, lo)]
            pts.extend(col)
        return np.array(pts, float)
    raise ValueError(f"unknown trajectory {kind!r}")


def resample_constant_speed(
    poly: np.ndarray, aspect: float, speed_heights_per_s: float, step_ms: float = PATH_STEP_MS
) -> list[tuple[float, float, float]]:
    """(t_ms, x, y) samples along `poly` at a constant on-screen speed."""
    if speed_heights_per_s <= 0:
        raise ValueError("speed must be positive")
    # On-screen distance in display heights: x is stretched by the aspect ratio.
    scaled = poly * np.array([aspect, 1.0])
    seg = np.hypot(*np.diff(scaled, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    total_s = s[-1] / speed_heights_per_s
    times = np.arange(0.0, total_s * 1000.0 + 1e-9, step_ms)
    dist = times / 1000.0 * speed_heights_per_s
    x = np.interp(dist, s, poly[:, 0])
    y = np.interp(dist, s, poly[:, 1])
    return [(float(t), float(a), float(b)) for t, a, b in zip(times, x, y, strict=True)]


def pursuit_plan(plan_id: str, request: dict) -> dict:
    poly = trajectory_polyline(request["trajectory"])
    lead = request["lead_in_ms"]
    samples = resample_constant_speed(poly, request["aspect"], request["speed"])
    path = [{"t_ms": 0.0, "position": {"x": samples[0][1], "y": samples[0][2]}}]
    path += [{"t_ms": lead + t, "position": {"x": x, "y": y}} for t, x, y in samples]
    return {
        "plan_id": plan_id,
        "purpose": request["purpose"],
        "duration_ms": float(path[-1]["t_ms"]),
        "body": {
            "method": "pursuit",
            "path": path,
            "lead_in_ms": lead,
            "trajectory": request["trajectory"],
        },
    }


def make_plan(plan_id: str, request: dict) -> dict:
    if request["method"] == "stationary":
        return stationary_plan(plan_id, request)
    if request["method"] == "pursuit":
        return pursuit_plan(plan_id, request)
    raise ValueError(f"unknown method {request['method']!r}")
