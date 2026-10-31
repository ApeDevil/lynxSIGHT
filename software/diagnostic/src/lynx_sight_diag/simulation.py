"""A deterministic simulated user in front of simulated cameras, for testing without hardware.

`SyntheticUser` produces the `FeatureSample`s two cameras would deliver while a person looks at
presented targets: with saccade latency and fixation jitter on stationary targets, lag and
look-aways during pursuit, blinks, intervals with a lost eye, low-confidence frames, head
movement, a systematic gaze offset, feature drift (as if the rig had moved) and camera
dropouts, as configured by a `SyntheticScenario` (contract type).

Everything is a pure function of (scenario, seed, time): random events are drawn per 10-second
block from a generator seeded with the block number, and per-frame noise from a generator
seeded with the frame number, so the same request always yields the same samples, in any
order. The feature model is a smooth made-up mapping chosen to exercise the calibration code;
it is not a model of the OV9281 images, and results on it say nothing about real accuracy.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable

import numpy as np

from .features import EYES, EyeFeature, FeatureSample, HeadState

CAMERAS = ("cam_left", "cam_right")
BLOCK_NS = 10_000_000_000
SACCADE_LATENCY_MS = 200.0
SACCADE_DURATION_MS = 40.0
LAPSE_DURATION_MS = 600.0
LOW_CONFIDENCE_SHARE = 0.02

GazeFn = Callable[[int], tuple[float, float]]


def default_scenario() -> dict:
    """The contract's `SyntheticScenario::default()`, kept in step by the engine tests."""
    return {
        "cameras": 2,
        "fps": 60.0,
        "feature_noise": 0.004,
        "blink_interval_s": 4.0,
        "blink_duration_ms": 150.0,
        "eye_loss_per_min": 2.0,
        "eye_loss_duration_ms": 300.0,
        "display_latency_ms": 20.0,
        "pursuit_lag_ms": 60.0,
        "pursuit_lapse_fraction": 0.1,
        "gaze_offset": {"x": 0.0, "y": 0.0},
        "feature_drift": [0.0, 0.0],
        "head_translation": 0.02,
        "head_rotation_deg": 4.0,
        "head_period_s": 7.0,
        "disconnects": [],
    }


def ideal_scenario() -> dict:
    """No noise, no blinks, no losses, no head motion: for exact checks."""
    s = default_scenario()
    s.update(
        feature_noise=0.0, blink_interval_s=0.0, eye_loss_per_min=0.0, pursuit_lapse_fraction=0.0,
        head_translation=0.0, head_rotation_deg=0.0,
    )  # fmt: skip
    return s


class SyntheticUser:
    def __init__(self, scenario: dict, seed: int, origin_ns: int):
        self.s = scenario
        self.seed = int(seed)
        self.origin_ns = int(origin_ns)
        self.cameras = CAMERAS[: max(1, min(2, int(scenario["cameras"])))]
        self.period_ns = int(1e9 / scenario["fps"])
        rng = np.random.default_rng([self.seed, 0])
        # Per camera and eye: feature offset and gain, fixed for the simulated person and rig.
        self.mapping = {
            (c, e): (
                rng.normal([0.0, 0.0], 0.02),
                np.array([0.28, 0.20]) * rng.uniform(0.9, 1.1, 2),
            )
            for c in self.cameras
            for e in EYES
        }
        self._events: dict[tuple[str, int], list[tuple[int, int, int]]] = {}

    # --- random events ---------------------------------------------------------------------

    def _block_events(self, kind: str, block: int) -> list[tuple[int, int, int]]:
        """(start_ns, end_ns, tag) events of `kind` starting in `block`."""
        key = (kind, block)
        if key in self._events:
            return self._events[key]
        kinds = {"blink": 1, "lapse": 2}
        kinds.update({f"loss:{c}:{e}": 10 + i for i, (c, e) in enumerate(self.mapping)})
        rate_per_s, duration_ms = {
            "blink": (1 / self.s["blink_interval_s"] if self.s["blink_interval_s"] > 0 else 0,
                      self.s["blink_duration_ms"]),
            "lapse": (self.s["pursuit_lapse_fraction"] / (LAPSE_DURATION_MS / 1000),
                      LAPSE_DURATION_MS),
        }.get(kind, (self.s["eye_loss_per_min"] / 60, self.s["eye_loss_duration_ms"]))  # fmt: skip
        rng = np.random.default_rng([self.seed, kinds[kind], block + 2**31])
        n = rng.poisson(rate_per_s * BLOCK_NS / 1e9)
        starts = np.sort(rng.uniform(0, BLOCK_NS, n)) + self.origin_ns + block * BLOCK_NS
        events = [(int(t), int(t + duration_ms * 1e6), int(rng.integers(1 << 30))) for t in starts]
        self._events[key] = events
        return events

    def _active(self, kind: str, t_ns: int) -> tuple[int, int, int] | None:
        block = (t_ns - self.origin_ns) // BLOCK_NS
        for b in (block - 1, block):
            for ev in self._block_events(kind, b):
                if ev[0] <= t_ns < ev[1]:
                    return ev
        return None

    def disconnected(self, camera_id: str, t_ns: int) -> bool:
        rel_ms = (t_ns - self.origin_ns) / 1e6
        return any(
            d["camera_id"] == camera_id
            and d["after_ms"] <= rel_ms < d["after_ms"] + d["duration_ms"]
            for d in self.s["disconnects"]
        )

    # --- head ------------------------------------------------------------------------------

    def head(self, t_ns: int, mode: str = "calibration") -> tuple[float, float, float, float]:
        """(x, y) translation in normalized image units and (yaw, pitch) in degrees."""
        amp_t, amp_r = self.s["head_translation"], self.s["head_rotation_deg"]
        if mode == "pose_range":
            amp_t, amp_r = max(amp_t, 0.06), max(amp_r, 15.0)
        elif mode == "still":
            amp_t, amp_r = amp_t * 0.1, amp_r * 0.1
        w = 2 * math.pi * (t_ns - self.origin_ns) / 1e9 / max(self.s["head_period_s"], 0.1)
        return (
            amp_t * math.sin(w),
            0.5 * amp_t * math.sin(1.3 * w + 1.0),
            amp_r * math.sin(0.8 * w + 0.5),
            0.6 * amp_r * math.sin(1.1 * w + 2.0),
        )

    # --- gaze ------------------------------------------------------------------------------

    def gaze_for_presentation(self, presentation: dict, method: str) -> GazeFn:
        frames = sorted(presentation["frames"], key=lambda f: f["t_ns"])
        t = np.array([f["t_ns"] for f in frames], np.int64)
        xy = np.array([[f["position"]["x"], f["position"]["y"]] for f in frames], float)
        offset = np.array([self.s["gaze_offset"]["x"], self.s["gaze_offset"]["y"]])
        display_ns = int(self.s["display_latency_ms"] * 1e6)
        if method == "pursuit":
            lag_ns = display_ns + int(self.s["pursuit_lag_ms"] * 1e6)

            def pursuit(t_ns: int) -> tuple[float, float]:
                lapse = self._active("lapse", t_ns)
                if lapse is not None:
                    r = np.random.default_rng([self.seed, 3, lapse[2]])
                    return tuple(r.uniform(0.1, 0.9, 2))
                q = t_ns - lag_ns
                g = np.array([np.interp(q, t, xy[:, 0]), np.interp(q, t, xy[:, 1])]) + offset
                return float(g[0]), float(g[1])

            return pursuit
        # Stationary: one saccade per target change, after the reaction latency.
        changes = [0] + [i for i in range(1, len(frames)) if not np.allclose(xy[i], xy[i - 1])]
        onsets = [int(t[i]) + display_ns + int(SACCADE_LATENCY_MS * 1e6) for i in changes]
        sacc_ns = int(SACCADE_DURATION_MS * 1e6)

        def stationary(t_ns: int) -> tuple[float, float]:
            k = bisect_right(onsets, t_ns) - 1
            if k < 0:
                g = np.array([0.5, 0.5])
            else:
                g = xy[changes[k]]
                into = t_ns - onsets[k]
                if into < sacc_ns:
                    prev = xy[changes[k - 1]] if k > 0 else np.array([0.5, 0.5])
                    g = prev + (g - prev) * into / sacc_ns
            g = g + offset
            # Fixational drift: slow, small, deterministic.
            ph = (t_ns - self.origin_ns) / 1e9
            g = g + 0.002 * np.array([math.sin(3.1 * ph), math.cos(2.3 * ph)])
            return float(g[0]), float(g[1])

        return stationary

    @staticmethod
    def fixate_centre(_t_ns: int) -> tuple[float, float]:
        return 0.5, 0.5

    # --- samples ---------------------------------------------------------------------------

    def frame_times(self, camera_index: int, start_ns: int, end_ns: int) -> range:
        phase = camera_index * self.period_ns // 3  # the cameras are not synchronised
        first = math.ceil((start_ns - self.origin_ns - phase) / self.period_ns)
        last = math.floor((end_ns - self.origin_ns - phase) / self.period_ns)
        return range(max(first, 0), last + 1)

    def samples(
        self, start_ns: int, end_ns: int, gaze: GazeFn, head_mode: str = "calibration"
    ) -> list[FeatureSample]:
        out = []
        for ci, cam in enumerate(self.cameras):
            phase = ci * self.period_ns // 3
            for k in self.frame_times(ci, start_ns, end_ns):
                t_ns = self.origin_ns + phase + k * self.period_ns
                if self.disconnected(cam, t_ns):
                    continue
                out.append(self.sample(cam, k, t_ns, gaze(t_ns), head_mode))
        out.sort(key=lambda s: (s.t_ns, s.camera_id))
        return out

    def sample(
        self, cam: str, k: int, t_ns: int, gaze: tuple[float, float], head_mode: str
    ) -> FeatureSample:
        rng = np.random.default_rng([self.seed, 4, CAMERAS.index(cam), k])
        hx, hy, yaw, pitch = self.head(t_ns, head_mode)
        # The eye's rotation toward the target, relative to the head (made-up but smooth).
        ex = (gaze[0] - 0.5) - 1.5 * hx - yaw / 40.0
        ey = (gaze[1] - 0.5) - 1.5 * hy - pitch / 40.0
        blinking = self._active("blink", t_ns) is not None
        drift = np.asarray(self.s["feature_drift"], float)
        noise = self.s["feature_noise"]
        low_conf = rng.uniform() < LOW_CONFIDENCE_SHARE
        eyes = []
        for eye in EYES:
            if self._active(f"loss:{cam}:{eye}", t_ns) is not None:
                eyes.append(EyeFeature(eye, None, None, 0.0))
                continue
            off, gain = self.mapping[(cam, eye)]
            u = off[0] + gain[0] * ex + 0.08 * ex * ex + 0.03 * ex * ey
            v = off[1] + gain[1] * ey + 0.05 * ey * ey
            iris = np.array([u, v]) + drift
            if noise:
                iris = iris + rng.normal(0, noise, 2)
            openness = 0.28 + (rng.normal(0, 0.01) if noise else 0.0)
            if blinking:
                iris = iris + np.array([0.0, 0.08])  # the lid drags the estimate down
                openness = 0.03
            conf = 0.3 if low_conf else 0.9
            eyes.append(EyeFeature(eye, (float(iris[0]), float(iris[1])), float(openness), conf))
        parallax = 0.05 if cam == "cam_left" else -0.05
        head = HeadState(
            x=0.5 - 0.8 * hx + parallax,
            y=0.45 - 0.8 * hy,
            scale_px=180.0 * (1 + 0.02 * math.sin(k / 50)),
            yaw_deg=yaw + (rng.normal(0, 0.5) if noise else 0.0),
            pitch_deg=pitch + (rng.normal(0, 0.5) if noise else 0.0),
            roll_deg=0.0,
        )
        return FeatureSample(t_ns, cam, 0.3 if low_conf else 0.95, tuple(eyes), head)
