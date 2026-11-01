"""Stereo geometry of the two cameras, and what it makes possible: metric 3-D face points,
head pose and head-pose-compensated gaze.

    board.py      printable checkerboard and its corner detection
    calibrate.py  intrinsics per camera + extrinsics between them, saved as
                  `lynx-sight/stereo-calibration/v1` JSON
    capture.py    choosing still, varied board views from both live cameras
    rig.py        the calibrated rig: rig frame, projection, triangulation
    head.py       head pose from triangulated MediaPipe landmarks against the user's template
    gaze.py       gaze as a ray from the eye in head coordinates, intersected with the screen

Frames and units follow docs/architecture/coordinate-systems.md: millimetres, the rig frame
(origin between the optical centres, X to the user's right, Y up, Z toward the user) and the
OpenCV camera frame. The cameras are not hardware-synchronised: everything that combines the two
images pairs frames by capture time and records the skew.
"""
