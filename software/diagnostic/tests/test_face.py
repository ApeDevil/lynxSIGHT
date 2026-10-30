import numpy as np

from lynx_sight_diag.processing import Result
from lynx_sight_diag.processing.eyes import EyesProcessor, eye_roi
from lynx_sight_diag.processing.face import Face, FaceProcessor, Faces, parse_yunet


def test_yunet_rows_become_faces_named_by_image_position():
    # box, right eye (subject) = image right? YuNet gives the subject's right eye first, which
    # appears on the image left for a non-mirrored camera; naming must not depend on that.
    row = np.array(
        [[100, 50, 80, 100, 160, 90, 120, 90, 140, 110, 155, 130, 125, 130, 0.93]], np.float32
    )
    (face,) = parse_yunet(row, scale=2.0)
    assert face.box == (200, 100, 160, 200)
    assert face.landmarks["eye_image_left"] == (240, 180)
    assert face.landmarks["eye_image_right"] == (320, 180)
    assert face.landmarks["mouth_image_left"] == (250, 260)
    assert abs(face.score - 0.93) < 1e-6
    assert face.eye_distance_px == 80
    assert parse_yunet(None, 1.0) == []


def test_face_processor_runs_on_monochrome_frames(make_frame):
    faces = FaceProcessor(input_width=320).process(make_frame(np.full((400, 640), 90, np.uint8)))
    assert faces.faces == [] and faces.best is None


def test_eye_regions_follow_landmarks_and_clip_at_borders(make_frame):
    frame = make_frame(np.full((400, 640), 120, np.uint8))
    face = Face(
        (200, 100, 200, 220),
        0.9,
        {
            "eye_image_left": (250.0, 180.0),
            "eye_image_right": (350.0, 190.0),
            "nose": (300, 230),
            "mouth_image_left": (260, 280),
            "mouth_image_right": (340, 280),
        },
    )
    eyes = EyesProcessor().process(frame, Result("face", "cam_left", frame, 0, 0, Faces([face])))
    assert len(eyes.regions) == 2
    assert eyes.regions[0].roi == (220, 160, 60, 40)
    assert eyes.regions[0].pupil is None  # uniform image
    assert abs(eyes.roll_deg - 5.71) < 0.01
    assert abs(eyes.eye_distance_px - 100.5) < 0.1
    assert eye_roi((5, 5), 60, 40, (400, 640)) == (0, 0, 35, 25)  # clipped
    assert eye_roi((-10, 5), 60, 40, (400, 640)) is None  # mostly outside
    assert (
        EyesProcessor().process(frame, Result("face", "cam_left", frame, 0, 0, Faces([]))) is None
    )
