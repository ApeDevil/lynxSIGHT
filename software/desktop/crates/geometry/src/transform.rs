//! Transforms between normalized display, display pixels, desktop and physical display
//! coordinates, and the [`MetricScale`] handed to the engine.

use lynx_sight_contracts::calibration::MetricScale;
use lynx_sight_contracts::display::{
    Display, DisplayCalibration, DisplayLayout, Rotation, ScreenPose,
};
use lynx_sight_contracts::metric::NormPoint;
use lynx_sight_contracts::pointer::DesktopPoint;

use crate::vec3::{self, Vec3};

/// The display's visible size in device pixels, after rotation.
pub fn visible_px(display: &Display) -> (u32, u32) {
    let (w, h) = (display.mode.width, display.mode.height);
    match display.rotation {
        Rotation::Deg0 | Rotation::Deg180 => (w, h),
        Rotation::Deg90 | Rotation::Deg270 => (h, w),
    }
}

/// The active area's visible size in millimetres, after rotation, if known.
pub fn visible_mm(display: &Display) -> Option<(f64, f64)> {
    let p = display.physical?;
    Some(match display.rotation {
        Rotation::Deg0 | Rotation::Deg180 => (p.width_mm, p.height_mm),
        Rotation::Deg90 | Rotation::Deg270 => (p.height_mm, p.width_mm),
    })
}

pub fn norm_to_display_px(display: &Display, p: NormPoint) -> (f64, f64) {
    let (w, h) = visible_px(display);
    (p.x * f64::from(w), p.y * f64::from(h))
}

pub fn display_px_to_norm(display: &Display, x: f64, y: f64) -> NormPoint {
    let (w, h) = visible_px(display);
    NormPoint {
        x: x / f64::from(w),
        y: y / f64::from(h),
    }
}

/// Normalized display point to desktop coordinates (desktop units, may be negative).
pub fn norm_to_desktop(display: &Display, p: NormPoint) -> DesktopPoint {
    let r = display.desktop;
    DesktopPoint {
        x: f64::from(r.x) + p.x * f64::from(r.width),
        y: f64::from(r.y) + p.y * f64::from(r.height),
    }
}

pub fn desktop_to_norm(display: &Display, p: DesktopPoint) -> NormPoint {
    let r = display.desktop;
    NormPoint {
        x: (p.x - f64::from(r.x)) / f64::from(r.width),
        y: (p.y - f64::from(r.y)) / f64::from(r.height),
    }
}

/// The display containing a desktop point, and the point in its normalized coordinates.
pub fn display_at(layout: &DisplayLayout, p: DesktopPoint) -> Option<(&Display, NormPoint)> {
    layout.displays.iter().find_map(|d| {
        let n = desktop_to_norm(d, p);
        ((0.0..1.0).contains(&n.x) && (0.0..1.0).contains(&n.y)).then_some((d, n))
    })
}

/// Normalized display point to the physical display frame (mm, x right, y down), if the
/// display's physical size is known.
pub fn norm_to_physical_mm(display: &Display, p: NormPoint) -> Option<(f64, f64)> {
    let (w, h) = visible_mm(display)?;
    Some((p.x * w, p.y * h))
}

/// A point of the physical display frame (mm; z into the screen) in the rig frame.
pub fn physical_to_rig(pose: &ScreenPose, p: Vec3) -> Vec3 {
    let z = vec3::cross(pose.x_axis, pose.y_axis);
    vec3::add(
        pose.origin_mm,
        vec3::add(
            vec3::add(
                vec3::scale(pose.x_axis, p[0]),
                vec3::scale(pose.y_axis, p[1]),
            ),
            vec3::scale(z, p[2]),
        ),
    )
}

/// A rig-frame point in the physical display frame (mm; z into the screen, so the user's eyes
/// have negative z).
pub fn rig_to_physical(pose: &ScreenPose, p: Vec3) -> Vec3 {
    let d = vec3::sub(p, pose.origin_mm);
    let z = vec3::cross(pose.x_axis, pose.y_axis);
    [
        vec3::dot(d, pose.x_axis),
        vec3::dot(d, pose.y_axis),
        vec3::dot(d, z),
    ]
}

/// The nominal pose of a display below a monitor-top rig, centred under it: the rig origin is
/// `above_mm` above the active area's top edge, and the screen plane is `behind_mm` behind the
/// rig origin (away from the user). A starting point for the user to correct, marked as
/// assumed.
pub fn screen_pose_below_rig(
    display: &Display,
    above_mm: f64,
    behind_mm: f64,
) -> Option<ScreenPose> {
    let (w, _) = visible_mm(display)?;
    Some(ScreenPose {
        origin_mm: [-w / 2.0, -above_mm, -behind_mm],
        x_axis: [1.0, 0.0, 0.0],
        y_axis: [0.0, -1.0, 0.0],
        provenance: lynx_sight_contracts::metric::Provenance::Assumed,
    })
}

/// Everything the engine needs to express errors in pixels, millimetres and degrees.
///
/// The eye midpoint is taken on the rig's Z axis at the viewing distance (the user faces the
/// rig, as the shared interface defines `user_distance_mm`).
pub fn metric_scale(cal: &DisplayCalibration) -> MetricScale {
    let (width_px, height_px) = visible_px(&cal.display);
    let mm = visible_mm(&cal.display);
    let eye_position_mm = match (cal.screen_pose, cal.viewing_distance_mm, mm) {
        (Some(pose), Some(distance), Some(_)) => Some(rig_to_physical(&pose, [0.0, 0.0, distance])),
        _ => None,
    };
    MetricScale {
        width_px,
        height_px,
        width_mm: mm.map(|m| m.0),
        height_mm: mm.map(|m| m.1),
        eye_position_mm,
    }
}
