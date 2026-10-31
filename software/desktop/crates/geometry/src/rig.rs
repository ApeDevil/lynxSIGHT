//! Camera frame ↔ rig frame from the mount's mechanical settings
//! (`docs/architecture/shared-interface.md`). Nominal geometry only: stereo calibration will
//! replace it with measured extrinsics.

use crate::vec3::{self, Vec3};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CameraSide {
    /// `cam_left`: on the user's left, at negative rig X.
    Left,
    Right,
}

/// Rotation (columns: camera x, y, z axes in the rig frame) and position of a camera.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CameraPose {
    pub axes: [Vec3; 3],
    pub position_mm: Vec3,
}

impl CameraPose {
    /// From the baseline and the mechanical angles: yaw > 0 turns toward the rig centre,
    /// pitch > 0 tilts up. With both zero the camera looks along rig +Z (at the user), so its
    /// image x (right in the image) is the user's left, rig -X, and image y (down) is rig -Y.
    pub fn nominal(side: CameraSide, baseline_mm: f64, yaw_deg: f64, pitch_deg: f64) -> Self {
        let sign = match side {
            CameraSide::Left => -1.0,
            CameraSide::Right => 1.0,
        };
        // Toe-in turns the optical axis toward x = 0: left camera toward +X, right toward -X.
        let yaw = (-sign) * yaw_deg.to_radians();
        let pitch = pitch_deg.to_radians();
        let z = [
            yaw.sin() * pitch.cos(),
            pitch.sin(),
            yaw.cos() * pitch.cos(),
        ];
        // Image y points down and stays perpendicular to the optical axis: rig "up" projected.
        let up = vec3::sub(
            [0.0, 1.0, 0.0],
            vec3::scale(z, vec3::dot([0.0, 1.0, 0.0], z)),
        );
        let y = vec3::scale(up, -1.0 / vec3::norm(up));
        let x = vec3::cross(y, z);
        CameraPose {
            axes: [x, y, z],
            position_mm: [sign * baseline_mm / 2.0, 0.0, 0.0],
        }
    }

    pub fn camera_to_rig(&self, p: Vec3) -> Vec3 {
        let [x, y, z] = self.axes;
        vec3::add(
            self.position_mm,
            vec3::add(
                vec3::add(vec3::scale(x, p[0]), vec3::scale(y, p[1])),
                vec3::scale(z, p[2]),
            ),
        )
    }

    pub fn rig_to_camera(&self, p: Vec3) -> Vec3 {
        let d = vec3::sub(p, self.position_mm);
        let [x, y, z] = self.axes;
        [vec3::dot(d, x), vec3::dot(d, y), vec3::dot(d, z)]
    }
}
