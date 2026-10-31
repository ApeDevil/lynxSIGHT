"""Shared helpers for the calibration tests: a simulated presenter and a full synthetic run."""

from __future__ import annotations

from lynx_sight_diag.calibration import alignment, targets
from lynx_sight_diag.simulation import SyntheticUser

ASPECT = 16 / 9
SCALE = {"width_px": 2560, "height_px": 1440, "width_mm": 597.0, "height_mm": 336.0,
         "eye_position_mm": [298.5, -30.0, -615.0]}  # fmt: skip
SCALE_PX_ONLY = {"width_px": 2560, "height_px": 1440, "width_mm": None, "height_mm": None,
                 "eye_position_mm": None}  # fmt: skip


def stationary_request(purpose="fit", layout=None, settle=700, dwell=1200):
    layout = layout or {"layout": "grid", "cols": 4, "rows": 3, "margin": 0.08}
    return {"method": "stationary", "purpose": purpose, "layout": layout, "settle_ms": settle,
            "dwell_ms": dwell, "aspect": ASPECT}  # fmt: skip


def pursuit_request(purpose="fit", trajectory=None, speed=0.25):
    trajectory = trajectory or {"trajectory": "spiral", "turns": 3, "margin": 0.08}
    return {"method": "pursuit", "purpose": purpose, "trajectory": trajectory, "speed": speed,
            "lead_in_ms": 800, "aspect": ASPECT}  # fmt: skip


def present(plan: dict, start_ns: int, refresh_hz: float = 60.0, pause=None) -> dict:
    """What a presenter at `refresh_hz` would report. `pause=(at_ms, length_ms)` splits the
    presentation into two spans; the plan's clock stops during the pause."""
    period = 1e9 / refresh_hz
    body = plan["body"]
    frames, spans = [], []
    t = float(start_ns)
    plan_ms = 0.0
    span_start = start_ns
    paused = False

    def position(ms):
        if body["method"] == "stationary":
            per = body["settle_ms"] + body["dwell_ms"]
            i = min(int(ms // per), len(body["targets"]) - 1)
            return body["targets"][i]["position"], i
        path = body["path"]
        k = max(j for j in range(len(path)) if path[j]["t_ms"] <= ms) if ms > 0 else 0
        return path[k]["position"], None

    while plan_ms < plan["duration_ms"]:
        if pause and not paused and plan_ms >= pause[0]:
            spans.append({"start_ns": span_start, "end_ns": int(t)})
            t += pause[1] * 1e6
            span_start = int(t)
            paused = True
        pos, idx = position(plan_ms)
        frames.append({"t_ns": int(t), "position": pos, "target_index": idx})
        t += period
        plan_ms += period / 1e6
    spans.append({"start_ns": span_start, "end_ns": int(t)})
    return {"plan_id": plan["plan_id"], "frames": frames, "spans": spans, "completed": True,
            "clock": "monotonic", "clock_uncertainty_ms": None}  # fmt: skip


def collect(user: SyntheticUser, plan: dict, start_ns: int, **kw):
    presentation = present(plan, start_ns, **kw)
    method = plan["body"]["method"]
    gaze = user.gaze_for_presentation(presentation, method)
    end = presentation["spans"][-1]["end_ns"]
    samples = user.samples(start_ns, end, gaze)
    return alignment.align(plan, presentation, samples), end


def full_run(scenario: dict, seed: int = 1):
    """Fit (stationary grid + spiral) and validation collections on the synthetic user."""
    user = SyntheticUser(scenario, seed, 0)
    t = 1_000_000_000
    out = {}
    for name, request in (
        ("grid", stationary_request()),
        ("spiral", pursuit_request()),
        ("validation", stationary_request("validation",
            {"layout": "validation_offset_grid", "cols": 4, "rows": 3, "margin": 0.08})),
    ):  # fmt: skip
        plan = targets.make_plan(name, request)
        out[name], t = collect(user, plan, t)
        t += 500_000_000
    return user, out
