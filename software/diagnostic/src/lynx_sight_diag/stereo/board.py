"""The calibration checkerboard: its geometry, a printable drawing and corner detection.

A board is named by its inner corners and square size, e.g. ``9x6@25`` (9 x 6 inner corners,
10 x 7 squares of 25 mm). One odd and one even square count make the pattern asymmetric, and the
corner order is normalised (first corner nearest the image's top-left) so both cameras number the
corners of one view the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

MM_PER_INCH = 25.4


@dataclass(frozen=True)
class Checkerboard:
    cols: int  # inner corners along the long side
    rows: int  # inner corners along the short side
    square_mm: float

    @classmethod
    def parse(cls, text: str) -> Checkerboard:
        """'9x6@25' -> 9 x 6 inner corners, 25 mm squares."""
        match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*@\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*", text)
        if not match:
            raise ValueError(f"board must look like 9x6@25 (inner corners @ square mm): {text!r}")
        cols, rows, square = int(match[1]), int(match[2]), float(match[3])
        if cols < 3 or rows < 3 or square <= 0:
            raise ValueError("a board needs at least 3 x 3 inner corners and a positive square")
        return cls(cols, rows, square)

    @property
    def spec(self) -> str:
        return f"{self.cols}x{self.rows}@{self.square_mm:g}"

    @property
    def pattern_size(self) -> tuple[int, int]:
        return (self.cols, self.rows)

    @property
    def size_mm(self) -> tuple[float, float]:
        """Outer size of the squares (not the paper)."""
        return ((self.cols + 1) * self.square_mm, (self.rows + 1) * self.square_mm)

    def object_points(self) -> np.ndarray:
        """(cols*rows, 3) corner positions on the board plane (z = 0) in mm, OpenCV order."""
        grid = np.mgrid[0 : self.cols, 0 : self.rows].T.reshape(-1, 2) * self.square_mm
        return np.column_stack([grid, np.zeros(len(grid))]).astype(np.float32)

    def to_dict(self) -> dict:
        return {"cols": self.cols, "rows": self.rows, "square_mm": self.square_mm}

    @classmethod
    def from_dict(cls, data: dict) -> Checkerboard:
        return cls(int(data["cols"]), int(data["rows"]), float(data["square_mm"]))


DEFAULT_BOARD = Checkerboard(9, 6, 25.0)  # squares 250 x 175 mm: fits A4 landscape


def _squares(board: Checkerboard):
    """(column, row) of the black squares; the top-left square is black."""
    for r in range(board.rows + 1):
        for c in range(board.cols + 1):
            if (r + c) % 2 == 0:
                yield c, r


def render_svg(board: Checkerboard, paper_mm: tuple[float, float] = (297.0, 210.0)) -> str:
    """The board centred on a page, in millimetres, with a 100 mm scale bar to check the print."""
    pw, ph = paper_mm
    bw, bh = board.size_mm
    if bw > pw - 10 or bh > ph - 22:
        raise ValueError(f"board {bw:g} x {bh:g} mm does not fit on {pw:g} x {ph:g} mm paper")
    x0, y0 = (pw - bw) / 2, (ph - bh) / 2 - 4
    s = board.square_mm
    rects = "\n".join(
        f'<rect x="{x0 + c * s:.3f}" y="{y0 + r * s:.3f}" width="{s:g}" height="{s:g}"/>'
        for c, r in _squares(board)
    )
    bar_y = y0 + bh + 6
    label = (
        f"LYNX SIGHT calibration board {board.spec}: {board.cols} x {board.rows} inner corners, "
        f"{s:g} mm squares. Print at 100 % (no fit-to-page), check the bar is 100 mm, "
        "measure a square and glue flat onto card."
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{pw:g}mm" height="{ph:g}mm"
 viewBox="0 0 {pw:g} {ph:g}">
<rect x="0" y="0" width="{pw:g}" height="{ph:g}" fill="white"/>
<g fill="black" shape-rendering="crispEdges">
{rects}
</g>
<rect x="{x0:.3f}" y="{bar_y:.3f}" width="100" height="1.5" fill="black"/>
<text x="{x0:.3f}" y="{bar_y + 6:.3f}" font-family="sans-serif" font-size="3">100 mm</text>
<text x="{x0:.3f}" y="{bar_y + 11:.3f}" font-family="sans-serif" font-size="2.6">{label}</text>
</svg>
"""


def render_image(board: Checkerboard, px_per_mm: float, margin_squares: float = 1.0) -> np.ndarray:
    """The board as an 8-bit image with a white margin; used for screens and synthetic views."""
    bw, bh = board.size_mm
    margin = margin_squares * board.square_mm
    width, height = round((bw + 2 * margin) * px_per_mm), round((bh + 2 * margin) * px_per_mm)
    image = np.full((height, width), 255, np.uint8)
    s = board.square_mm * px_per_mm
    m = margin * px_per_mm
    for c, r in _squares(board):
        x, y = m + c * s, m + r * s
        image[round(y) : round(y + s), round(x) : round(x + s)] = 0
    return image


def find_corners(image: np.ndarray, board: Checkerboard) -> np.ndarray | None:
    """Sub-pixel inner corners (cols*rows, 2) in a grey image, or None if the whole board is not
    visible. Uses OpenCV's sector-based detector, which is more accurate and robust to blur than
    the classic one and needs no separate sub-pixel refinement."""
    found, corners = cv2.findChessboardCornersSB(
        image, board.pattern_size, flags=cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE
    )
    if not found or corners is None:
        return None
    return normalise_order(corners.reshape(-1, 2).astype(np.float32))


def normalise_order(corners: np.ndarray) -> np.ndarray:
    """Reverses the corner list when it starts at the image's bottom-right, so two nearly
    parallel cameras number the corners of the same board view identically."""
    first, last = corners[0], corners[-1]
    return corners[::-1].copy() if first.sum() > last.sum() else corners
