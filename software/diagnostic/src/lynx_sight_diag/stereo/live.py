"""Live preview of the head-ray gaze model: a dot where the model says the user is looking.

Pairs the newest MediaPipe result of each camera when their capture times are close, so the
dot moves at the landmarks rate. The shown point is the median of the last few predictions, a
deliberately simple smoother; no cursor is moved."""

from __future__ import annotations

import time
from collections import deque

import cv2
import numpy as np

from .gaze import HeadRayModel
from .head import observe, triangulate_face
from .rig import StereoRig

WINDOW = "LYNX SIGHT gaze preview"


def run_gaze_preview(
    session,
    rig: StereoRig,
    model: HeadRayModel,
    max_skew_ms: float = 20.0,
    smooth: int = 5,
    max_frames: int | None = None,
) -> dict:
    """Full-screen; Esc or q ends. Returns counts of pairs used and dropped."""
    width, height = model.screen.size_px
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    session.start()
    recent: deque = deque(maxlen=smooth)
    seen: tuple[int, int] | None = None
    stats = {"pairs": 0, "skew_too_large": 0, "no_estimate": 0, "frames": 0}
    scaled: StereoRig | None = None
    try:
        while max_frames is None or stats["frames"] < max_frames:
            stats["frames"] += 1
            left = session.board.latest("cam_left", "landmarks")
            right = session.board.latest("cam_right", "landmarks")
            status = "waiting for a face in both cameras"
            if (
                left is not None
                and right is not None
                and left.data is not None
                and right.data is not None
            ):
                key = (left.frame.seq, right.frame.seq)
                skew = (right.frame.t_capture_ns - left.frame.t_capture_ns) / 1e6
                if key != seen:
                    seen = key
                    if abs(skew) > max_skew_ms:
                        stats["skew_too_large"] += 1
                    else:
                        size = (left.frame.width, left.frame.height)
                        if scaled is None or scaled.left.image_size != size:
                            scaled = rig if rig.left.image_size == size else rig.scaled_to(size)
                        face = triangulate_face(scaled, left.data.points, right.data.points)
                        obs = observe(face, model.template)
                        point = model.predict(obs) if obs is not None else None
                        if point is None:
                            stats["no_estimate"] += 1
                        else:
                            stats["pairs"] += 1
                            recent.append(point)
                status = f"skew {skew:+.1f} ms"
            canvas = np.zeros((height, width, 3), np.uint8)
            if recent:
                x, y = np.median(np.array(recent), axis=0)
                if np.isfinite(x) and np.isfinite(y):
                    cv2.circle(canvas, (int(x), int(y)), 22, (0, 200, 255), 3)
            text = (
                f"{status}  pairs {stats['pairs']}  dropped (skew) {stats['skew_too_large']}"
                "  - Esc ends"
            )
            cv2.putText(canvas, text, (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (160, 160, 160), 2)
            cv2.imshow(WINDOW, canvas)
            if (cv2.waitKey(5) & 0xFF) in (27, ord("q")):
                break
            time.sleep(0.002)
    finally:
        session.stop()
        cv2.destroyWindow(WINDOW)
    return stats
