"""The calibrated two-camera rig: camera models, the rig frame, projection and triangulation.

`CameraModel` is one camera's intrinsics plus its pose in the rig frame. The rig frame is derived
from the calibration, not assumed: X points from cam_left's optical centre to cam_right's (the
user's right), Z is the mean optical axis made perpendicular to X and turned down by the
cameras' configured pitch (0 on the fixed rig), and Y = Z x X (up). The origin is the midpoint of
the two optical centres. So the stereo calibration measures the baseline and relative rotation,
and the configured mounting angles only enter through that pitch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

CAMERA_IDS = ("cam_left", "cam_right")


@dataclass(frozen=True)
class CameraModel:
    camera_id: str
    image_size: tuple[int, int]  # (width, height) px the intrinsics belong to
    K: np.ndarray  # (3, 3)
    dist: np.ndarray  # OpenCV distortion coefficients (k1, k2, p1, p2, k3)
    R_cam_from_rig: np.ndarray  # (3, 3)
    t_cam_from_rig: np.ndarray  # (3,): x_cam = R x_rig + t

    @property
    def centre_rig(self) -> np.ndarray:
        """Optical centre in rig coordinates."""
        return -self.R_cam_from_rig.T @ self.t_cam_from_rig

    def to_camera(self, points_rig: np.ndarray) -> np.ndarray:
        return np.atleast_2d(points_rig) @ self.R_cam_from_rig.T + self.t_cam_from_rig

    def project(self, points_rig: np.ndarray) -> np.ndarray:
        """(N, 3) rig mm -> (N, 2) distorted pixels."""
        rvec, _ = cv2.Rodrigues(self.R_cam_from_rig)
        px, _ = cv2.projectPoints(
            np.atleast_2d(points_rig).astype(np.float64),
            rvec,
            self.t_cam_from_rig,
            self.K,
            self.dist,
        )
        return px.reshape(-1, 2)

    def normalised(self, pixels: np.ndarray) -> np.ndarray:
        """(N, 2) pixels -> (N, 2) undistorted normalised image coordinates (z = 1)."""
        pts = np.asarray(pixels, np.float64).reshape(-1, 1, 2)
        return cv2.undistortPoints(pts, self.K, self.dist).reshape(-1, 2)

    def scaled_to(self, image_size: tuple[int, int]) -> CameraModel:
        """The same camera for another capture size with the same field of view (binning or
        scaling, not cropping)."""
        sx, sy = image_size[0] / self.image_size[0], image_size[1] / self.image_size[1]
        K = self.K.copy()
        # Pixel centres sit at integer coordinates, so the principal point scales about -0.5.
        K[0, 0], K[0, 2] = K[0, 0] * sx, (K[0, 2] + 0.5) * sx - 0.5
        K[1, 1], K[1, 2] = K[1, 1] * sy, (K[1, 2] + 0.5) * sy - 0.5
        return CameraModel(
            self.camera_id, image_size, K, self.dist, self.R_cam_from_rig, self.t_cam_from_rig
        )


def rig_axes_in_left(R: np.ndarray, T: np.ndarray, pitch_deg: float = 0.0) -> tuple:
    """Rig axes and origin expressed in cam_left's frame, from the stereo extrinsics
    (x_right = R x_left + T). Returns (A, origin) with x_rig = A @ (x_left - origin)."""
    centre_right = -R.T @ T
    x = centre_right / np.linalg.norm(centre_right)
    optical = (np.array([0.0, 0.0, 1.0]) + R.T @ np.array([0.0, 0.0, 1.0])) / 2
    z_opt = optical - (optical @ x) * x
    z_opt /= np.linalg.norm(z_opt)
    y_opt = np.cross(z_opt, x)
    p = math.radians(pitch_deg)
    z = math.cos(p) * z_opt - math.sin(p) * y_opt
    y = np.cross(z, x)
    return np.vstack([x, y, z]), centre_right / 2


@dataclass(frozen=True)
class StereoRig:
    left: CameraModel
    right: CameraModel

    @classmethod
    def from_extrinsics(
        cls,
        image_size: tuple[int, int],
        K_left: np.ndarray,
        dist_left: np.ndarray,
        K_right: np.ndarray,
        dist_right: np.ndarray,
        R: np.ndarray,
        T: np.ndarray,
        pitch_deg: float = 0.0,
    ) -> StereoRig:
        """From OpenCV stereo extrinsics (x_right = R x_left + T, mm)."""
        R, T = np.asarray(R, float), np.asarray(T, float).reshape(3)
        A, origin = rig_axes_in_left(R, T, pitch_deg)
        # x_left = A^T x_rig + origin; x_right = R x_left + T
        R_l, t_l = A.T, origin
        R_r, t_r = R @ A.T, R @ origin + T
        return cls(
            CameraModel(
                "cam_left",
                image_size,
                np.asarray(K_left, float),
                np.asarray(dist_left, float).ravel(),
                R_l,
                t_l,
            ),
            CameraModel(
                "cam_right",
                image_size,
                np.asarray(K_right, float),
                np.asarray(dist_right, float).ravel(),
                R_r,
                t_r,
            ),
        )

    @classmethod
    def nominal(cls, image_size=(1280, 800), baseline_mm=257.0, hfov_deg=70.0) -> StereoRig:
        """Ideal parallel cameras (no distortion) with the rig's nominal geometry; for
        simulation and as a stand-in, never as a measurement."""
        w, h = image_size
        f = w / 2 / math.tan(math.radians(hfov_deg) / 2)
        K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
        return cls.from_extrinsics(
            image_size, K, np.zeros(5), K, np.zeros(5), np.eye(3), np.array([baseline_mm, 0, 0])
        )

    def camera(self, camera_id: str) -> CameraModel:
        return {"cam_left": self.left, "cam_right": self.right}[camera_id]

    @property
    def baseline_mm(self) -> float:
        return float(np.linalg.norm(self.right.centre_rig - self.left.centre_rig))

    def scaled_to(self, image_size: tuple[int, int]) -> StereoRig:
        return StereoRig(self.left.scaled_to(image_size), self.right.scaled_to(image_size))

    def triangulate(
        self, px_left: np.ndarray, px_right: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Matching pixels of both cameras -> (N, 3) rig points in mm and (N,) the larger of the
        two reprojection errors in px (large for mismatched points)."""
        nl, nr = self.left.normalised(px_left), self.right.normalised(px_right)
        P_l = np.hstack([self.left.R_cam_from_rig, self.left.t_cam_from_rig[:, None]])
        P_r = np.hstack([self.right.R_cam_from_rig, self.right.t_cam_from_rig[:, None]])
        X = cv2.triangulatePoints(P_l, P_r, nl.T, nr.T)
        points = (X[:3] / X[3]).T
        err = np.maximum(
            np.linalg.norm(self.left.project(points) - np.asarray(px_left).reshape(-1, 2), axis=1),
            np.linalg.norm(
                self.right.project(points) - np.asarray(px_right).reshape(-1, 2), axis=1
            ),
        )
        return points, err
