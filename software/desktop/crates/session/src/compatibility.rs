//! Whether a profile's calibration still applies to the current setup.
//!
//! Hard mismatches (another display or mode, other cameras or features) make it
//! incompatible: only a full calibration helps. Soft changes (sitting closer or farther, a
//! head pose outside the calibrated range) degrade it: validate, or recalibrate quickly.

use lynx_sight_contracts::app::{Compatibility, CompatibilityStatus};
use lynx_sight_contracts::display::Display;
use lynx_sight_contracts::metric::Range;
use lynx_sight_contracts::profile::Profile;
use lynx_sight_contracts::tracking::TrackingStatus;

/// The setup the profile would be used with now.
pub struct Conditions<'a> {
    pub display: &'a Display,
    /// `"synthetic"` or `"cameras"`.
    pub source: &'a str,
    pub feature_set: &'a str,
    pub tracking: Option<&'a TrackingStatus>,
}

const DISTANCE_TOLERANCE: (f64, f64) = (0.85, 1.18);

pub fn assess(profile: &Profile, now: &Conditions) -> Compatibility {
    let mut hard = Vec::new();
    let mut soft = Vec::new();
    let then = &profile.display.display;
    let same_display = match (&then.id.stable, &now.display.id.stable) {
        (Some(a), Some(b)) => a == b,
        _ => then.id.connector == now.display.id.connector && then.mode == now.display.mode,
    };
    if !same_display {
        hard.push(format!(
            "calibrated on {}, now {}",
            then.name, now.display.name
        ));
    } else {
        if then.mode != now.display.mode || then.rotation != now.display.rotation {
            hard.push("the display mode or rotation changed".into());
        }
        if (then.scale_factor - now.display.scale_factor).abs() > 1e-6
            || then.desktop.width != now.display.desktop.width
        {
            soft.push(
                "the desktop scaling changed (the gaze model is unaffected; pointer mapping is)"
                    .into(),
            );
        }
    }
    if profile.rig.source != now.source {
        hard.push(format!(
            "calibrated with the {} source, now {}",
            profile.rig.source, now.source
        ));
    }
    if let Some(active) = &profile.active {
        if active.model.feature_set != now.feature_set {
            hard.push(format!(
                "the model uses {}, the engine delivers {}",
                active.model.feature_set, now.feature_set
            ));
        }
    } else {
        hard.push("no calibration yet".into());
    }
    let mut unknown = false;
    match (now.tracking, &profile.face_baseline) {
        (Some(t), Some(baseline)) if t.ready => {
            for cam in &t.cameras {
                let neutral = baseline
                    .cameras
                    .iter()
                    .find(|b| b.camera_id == cam.camera_id)
                    .and_then(|b| b.interocular_px.value());
                if let (Some(neutral), Some(now_px)) = (neutral, cam.interocular_px.value()) {
                    let rel = now_px / neutral;
                    if rel < DISTANCE_TOLERANCE.0 || rel > DISTANCE_TOLERANCE.1 {
                        soft.push(format!("{}: the face appears {:.0} % of its calibrated size (distance changed)", cam.camera_id, rel * 100.0));
                    }
                }
                if let (Some(pose), Some(range)) = (
                    cam.head_pose,
                    profile
                        .active
                        .as_ref()
                        .and_then(|a| a.coverage.as_ref())
                        .and_then(|c| c.yaw_deg),
                ) {
                    if !within(pose.yaw_deg, range, 3.0) {
                        soft.push(format!(
                            "{}: head yaw {:.0}° is outside the calibrated {:.0}..{:.0}°",
                            cam.camera_id, pose.yaw_deg, range.min, range.max
                        ));
                    }
                }
            }
        }
        (Some(_), Some(_)) => soft.push("both eyes are not tracked right now".into()),
        _ => unknown = true,
    }
    let status = if !hard.is_empty() {
        CompatibilityStatus::Incompatible
    } else if !soft.is_empty() {
        CompatibilityStatus::Degraded
    } else if unknown {
        CompatibilityStatus::Unknown
    } else {
        CompatibilityStatus::Compatible
    };
    if unknown && hard.is_empty() {
        soft.push("tracking or face baseline unavailable: compatibility unknown".into());
    }
    Compatibility {
        status,
        reasons: hard.into_iter().chain(soft).collect(),
    }
}

fn within(v: f64, r: Range, margin: f64) -> bool {
    v >= r.min - margin && v <= r.max + margin
}
