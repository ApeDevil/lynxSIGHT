"""Live checkerboard detection, for guiding the stereo calibration capture.

Detects on a half-resolution copy to keep up with the live view; the capture tool saves the
full-resolution frames and the solver detects the corners again on those."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..frames import Frame
from ..stereo.board import Checkerboard, normalise_order


@dataclass(frozen=True)
class BoardCorners:
    corners: np.ndarray  # (cols*rows, 2) full-resolution pixels, normalised order


class ChessboardProcessor:
    name = "chessboard"
    upstream = None

    def __init__(self, board: str = "9x6@25", detect_width: int = 640):
        self.board = Checkerboard.parse(board)
        self.detect_width = detect_width

    def process(self, frame: Frame, upstream=None) -> BoardCorners | None:
        image = frame.image
        scale = min(1.0, self.detect_width / frame.width)
        if scale < 1.0:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        found, corners = cv2.findChessboardCornersSB(
            image, self.board.pattern_size, flags=cv2.CALIB_CB_NORMALIZE_IMAGE
        )
        if not found or corners is None:
            return None
        pts = corners.reshape(-1, 2).astype(np.float32)
        if scale < 1.0:
            pts = (pts + 0.5) / scale - 0.5  # pixel centres at integer coordinates
        return BoardCorners(normalise_order(pts))
