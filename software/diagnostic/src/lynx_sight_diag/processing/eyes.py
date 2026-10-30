"""Dynamic eye regions from the face landmarks, plus pupil localisation inside each.

Runs downstream of `face`, on exactly the frame the face was found in. Eye regions are rectangles
centred on the YuNet eye landmarks with a side proportional to the inter-eye distance, so they
follow the head and scale with distance.

Positions are image measurements. `pupil_offset` (pupil minus eye-landmark centre, divided by
the inter-eye distance) is a scale-normalised feature for later gaze calibration, not a gaze.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..frames import Frame
from . import Result
from .face import Faces
from .pupil import Pupil, locate_pupil


@dataclass(frozen=True)
class EyeRegion:
    label: str  # "image_left" | "image_right"
    roi: tuple[int, int, int, int]  # x, y, w, h in full-resolution pixels
    landmark: tuple[float, float]
    pupil: Pupil | None  # coordinates relative to `roi`
    pupil_xy: tuple[float, float] | None  # full-resolution pixels
    pupil_offset: tuple[float, float] | None  # (pupil - landmark) / eye distance


@dataclass(frozen=True)
class Eyes:
    face_score: float
    eye_distance_px: float
    roll_deg: float  # in-plane head roll from the eye line (image measurement, uncalibrated)
    face_centre_norm: tuple[float, float]  # face box centre / image size, 0..1
    regions: list[EyeRegion]


def eye_roi(
    centre: tuple[float, float], width: float, height: float, shape: tuple[int, int]
) -> tuple[int, int, int, int] | None:
    """Region of width x height px around `centre`, clipped to the image; None if mostly outside."""
    h, w = shape
    x0, y0 = max(0, round(centre[0] - width / 2)), max(0, round(centre[1] - height / 2))
    x1, y1 = min(w, round(centre[0] + width / 2)), min(h, round(centre[1] + height / 2))
    if x1 - x0 < width * 0.5 or y1 - y0 < height * 0.5:
        return None
    return x0, y0, x1 - x0, y1 - y0


class EyesProcessor:
    name = "eyes"
    upstream = "face"

    # Region size relative to the inter-eye distance: wide enough for the whole eye opening,
    # low enough to leave out most of the eyebrow, which is dark like a pupil.
    def __init__(
        self, roi_width: float = 0.6, roi_height: float = 0.4, min_eye_distance_px: float = 20.0
    ):
        self.roi_width = roi_width
        self.roi_height = roi_height
        self.min_eye_distance_px = min_eye_distance_px

    def process(self, frame: Frame, upstream: Result | None) -> Eyes | None:
        faces: Faces | None = upstream.data if upstream else None
        face = faces.best if faces else None
        if face is None:
            return None
        iod = face.eye_distance_px
        (lx, ly), (rx, ry) = face.landmarks["eye_image_left"], face.landmarks["eye_image_right"]
        regions = []
        if iod >= self.min_eye_distance_px:
            for label, centre in (("image_left", (lx, ly)), ("image_right", (rx, ry))):
                roi = eye_roi(
                    centre, self.roi_width * iod, self.roi_height * iod, frame.image.shape
                )
                if roi is None:
                    continue
                x, y, w, h = roi
                crop = frame.image[y : y + h, x : x + w]  # a view: no copy
                pupil = locate_pupil(crop)
                xy = offset = None
                if pupil is not None:
                    xy = (x + pupil.x, y + pupil.y)
                    offset = ((xy[0] - centre[0]) / iod, (xy[1] - centre[1]) / iod)
                regions.append(EyeRegion(label, roi, centre, pupil, xy, offset))
        bx, by, bw, bh = face.box
        return Eyes(
            face_score=face.score,
            eye_distance_px=iod,
            roll_deg=math.degrees(math.atan2(ry - ly, rx - lx)),
            face_centre_norm=((bx + bw / 2) / frame.width, (by + bh / 2) / frame.height),
            regions=regions,
        )
