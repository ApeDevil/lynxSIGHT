//! Values that may be unknown, and points in normalized display coordinates.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

/// A measured or computed number, or the explicit reason it is not available.
///
/// Used instead of placeholder numbers: a quality or accuracy value that cannot be computed
/// (no physical display size, too few samples, ...) says so.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "status", rename_all = "snake_case")]
#[ts(export)]
pub enum Metric {
    Available { value: f64 },
    Unavailable { reason: String },
}

impl Metric {
    pub fn available(value: f64) -> Self {
        Metric::Available { value }
    }

    pub fn unavailable(reason: impl Into<String>) -> Self {
        Metric::Unavailable {
            reason: reason.into(),
        }
    }

    pub fn value(&self) -> Option<f64> {
        match self {
            Metric::Available { value } => Some(*value),
            Metric::Unavailable { .. } => None,
        }
    }
}

/// One error statistic in every unit the geometry supports. `px` is always computable (display
/// pixels); `mm` needs the physical display size; `deg` (visual angle) also needs the eye
/// position relative to the display.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct MetricSet {
    pub px: Metric,
    pub mm: Metric,
    pub deg: Metric,
}

/// A point in normalized display coordinates: (0, 0) is the top-left corner of the display's
/// visible image as the user sees it (after rotation), (1, 1) the bottom-right.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct NormPoint {
    pub x: f64,
    pub y: f64,
}

/// A closed range of a measured quantity.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Range {
    pub min: f64,
    pub max: f64,
}

/// Where a physical quantity comes from, so estimates are never mistaken for measurements.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum Provenance {
    /// Reported by the display's EDID; often rounded, sometimes wrong or zero.
    Edid,
    /// Reported by the operating system's display API.
    Platform,
    /// Measured by the user (ruler, calliper) and entered by hand.
    UserMeasured,
    /// Computed from a calibration procedure.
    Calibrated,
    /// A nominal design value nobody has measured.
    Assumed,
}
