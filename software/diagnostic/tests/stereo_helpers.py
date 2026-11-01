"""Synthetic stereo data: rendered checkerboard views and a simulated 3-D face.

Everything here is generated from known geometry, so tests can check that calibration and
head/gaze estimation recover it. It says nothing about the real cameras."""

from __future__ import annotations

import math

import cv2
import numpy as np

from lynx_sight_diag.stereo.board import Checkerboard, render_image
from lynx_sight_diag.stereo.rig import CameraModel, StereoRig

PX_PER_MM = 6.0


def rotation(yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0) -> np.ndarray:
    """Rotation about Y (yaw), then X (pitch), then Z (roll), in the rig frame."""
    y, p, r = (math.radians(v) for v in (yaw_deg, pitch_deg, roll_deg))
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    Rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def board_pose(centre_rig, yaw=0.0, pitch=0.0, roll=0.0, board=None):
    """(R_rig_from_board, t) placing the board's centre at `centre_rig`, facing the cameras.
    Board axes: x along the columns, y along the rows, z = x * y. Facing the cameras (which look
    along rig +Z from Z = 0), a board at Z > 0 has its normal toward -Z."""
    board = board or Checkerboard(9, 6, 25.0)
    # board x -> rig -X (as seen by the cameras: image right), board y -> rig -Y (image down)
    base = np.diag([-1.0, -1.0, 1.0])
    R = rotation(yaw, pitch, roll) @ base
    centre_board = np.array(
        [(board.cols - 1) * board.square_mm / 2, (board.rows - 1) * board.square_mm / 2, 0.0]
    )
    t = np.asarray(centre_rig, float) - R @ centre_board
    return R, t


def render_view(
    board: Checkerboard, camera: CameraModel, R_rig_board, t_rig_board, noise=2.0, seed=0
) -> np.ndarray:
    texture = render_image(board, PX_PER_MM, margin_squares=1.0)
    # Render 2x supersampled and box-filter down, so edges are not aliased.
    out_w, out_h = camera.image_size
    camera = camera.scaled_to((out_w * 2, out_h * 2))
    w, h = camera.image_size
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
    n = camera.normalised(np.column_stack([xs.ravel(), ys.ravel()]))
    R_cb = camera.R_cam_from_rig @ R_rig_board
    t_cb = camera.R_cam_from_rig @ t_rig_board + camera.t_cam_from_rig
    H = np.column_stack([R_cb[:, 0], R_cb[:, 1], t_cb])
    b = np.linalg.solve(H, np.column_stack([n, np.ones(len(n))]).T)
    bx, by = b[0] / b[2], b[1] / b[2]
    offset = board.square_mm * 2  # margin (1 square) + first square to the first inner corner
    map_x = ((bx + offset) * PX_PER_MM - 0.5).reshape(h, w).astype(np.float32)
    map_y = ((by + offset) * PX_PER_MM - 0.5).reshape(h, w).astype(np.float32)
    image = cv2.remap(texture, map_x, map_y, cv2.INTER_LINEAR, borderValue=200)
    image = cv2.resize(image, (out_w, out_h), interpolation=cv2.INTER_AREA)
    image = cv2.GaussianBlur(image, (0, 0), 0.6)
    rng = np.random.default_rng(seed)
    image = np.clip(image * 0.75 + 30 + rng.normal(0, noise, image.shape), 0, 255)
    return image.astype(np.uint8)


def make_rig(image_size=(640, 400)) -> StereoRig:
    """A slightly imperfect rig: distortion, toe-in, a small vertical offset."""
    w, h = image_size
    f = w / 2 / math.tan(math.radians(35))
    K_l = np.array([[f, 0, w / 2 + 3], [0, f * 1.002, h / 2 - 2], [0, 0, 1.0]])
    K_r = np.array([[f * 0.995, 0, w / 2 - 4], [0, f * 0.996, h / 2 + 3], [0, 0, 1.0]])
    d_l = np.array([-0.08, 0.05, 0.0005, -0.0003, 0.0])
    d_r = np.array([-0.06, 0.03, -0.0004, 0.0002, 0.0])
    R = rotation(-1.5, 0.4, 0.3)
    T = np.array([257.0, 1.2, -0.8])
    return StereoRig.from_extrinsics(image_size, K_l, d_l, K_r, d_r, R, T), R, T


def board_poses(n=16, seed=1):
    """Varied board poses 400-800 mm in front of the rig, tilted up to ~35 degrees."""
    rng = np.random.default_rng(seed)
    poses = []
    for i in range(n):
        z = 420 + (i % 4) * 110 + rng.uniform(-20, 20)
        x = rng.uniform(-0.4, 0.4) * z
        y = rng.uniform(-0.25, 0.25) * z
        poses.append(
            board_pose((x, y, z), rng.uniform(-35, 35), rng.uniform(-30, 30), rng.uniform(-15, 15))
        )
    return poses


# --- simulated face ----------------------------------------------------------------------------

EYEBALL_RADIUS_MM = 11.0  # rotation centre to iris centre
# Head frame: origin between the eye corners, X to the user's right, Y up, Z out of the back.
_FACE_MM = {
    # user's right eye (MediaPipe 33 outer, 133 inner) and left eye (362 inner, 263 outer)
    33: (47.0, 1.0, 8.0),
    133: (17.0, 0.0, 2.0),
    362: (-17.0, 0.0, 2.0),
    263: (-47.0, 1.0, 8.0),
    168: (0.0, 8.0, -8.0),
    6: (0.0, -6.0, -14.0),
    197: (0.0, -16.0, -19.0),
    195: (0.0, -26.0, -24.0),
    5: (0.0, -36.0, -29.0),
    4: (0.0, -44.0, -33.0),
    10: (0.0, 70.0, 2.0),
    151: (0.0, 52.0, -6.0),
    9: (0.0, 36.0, -9.0),
    8: (0.0, 24.0, -10.0),
    107: (14.0, 22.0, -6.0),
    336: (-14.0, 22.0, -6.0),
    # lids (for openness), not used by the 3-D code
    159: (32.0, 6.0, 0.0),
    145: (32.0, -6.0, 0.0),
    386: (-32.0, 6.0, 0.0),
    374: (-32.0, -6.0, 0.0),
}
EYEBALLS = {468: np.array([32.0, 0.5, 13.0]), 473: np.array([-32.0, 0.5, 13.0])}
KAPPA_DEG = {468: (-4.0, 1.5), 473: (4.0, 1.5)}  # optical vs visual axis per eye (yaw, pitch)


def face_points_rig(R_head, t_head, target_rig) -> np.ndarray:
    """(478, 3) rig mm of a face looking at `target_rig`; unused landmarks sit on the nose."""
    pts_h = np.tile(np.array([0.0, -20.0, -20.0]), (478, 1))
    for i, p in _FACE_MM.items():
        pts_h[i] = p
    pts = pts_h @ R_head.T + t_head
    for iris, centre_h in EYEBALLS.items():
        centre = R_head @ centre_h + t_head
        visual = (target_rig - centre) / np.linalg.norm(target_rig - centre)
        # optical axis = visual axis turned by kappa, in head coordinates
        k_yaw, k_pitch = KAPPA_DEG[iris]
        optical = R_head @ rotation(k_yaw, k_pitch) @ R_head.T @ visual
        pts[iris] = centre + EYEBALL_RADIUS_MM * optical
    return pts


def observe_face(rig: StereoRig, R_head, t_head, target_rig, rng, noise_px=0.3):
    """MediaPipe-like (478, 2) landmarks per camera, with pixel noise."""
    pts = face_points_rig(R_head, t_head, target_rig)
    out = {}
    for cid in ("cam_left", "cam_right"):
        px = rig.camera(cid).project(pts)
        out[cid] = (px + rng.normal(0, noise_px, px.shape)).astype(np.float32)
    return out
