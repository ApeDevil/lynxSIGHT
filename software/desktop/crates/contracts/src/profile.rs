//! The persisted calibration profile (schema `lynx-sight/profile`, version
//! [`crate::PROFILE_SCHEMA_VERSION`]).
//!
//! A profile holds derived parameters only. Raw camera images, face images and recordings are
//! never part of it; diagnostic recordings are a separate, explicit action of `sight-diag`.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::calibration::{CollectionSummary, GazeModel, TrainingSummary, ValidationReport};
use crate::display::DisplayCalibration;
use crate::metric::Metric;
use crate::tracking::{FaceBaseline, PoseCoverage};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct CameraBinding {
    pub camera_id: String,
    /// Stable device path (`/dev/v4l/by-path/...`): the two cameras share a USB serial, so the
    /// USB port identifies them.
    pub device: String,
    pub serial: Option<String>,
    /// Negotiated mode, e.g. `MJPG 1280x800@120`.
    pub mode: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct RigConfig {
    /// `"synthetic"` or `"cameras"`.
    pub source: String,
    pub baseline_mm: Option<f64>,
    pub cameras: Vec<CameraBinding>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum Workflow {
    Full,
    Quick,
    Incremental,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum RecordStatus {
    Active,
    /// Was active and has been replaced by a better one.
    Superseded,
    /// A candidate the user or the comparison declined.
    Rejected,
}

/// Conditions at calibration time, for judging later whether the model still applies.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Environment {
    pub camera_modes: Vec<String>,
    /// Mean image level 0..255 across cameras, if measured.
    pub mean_image_level: Metric,
    pub background_brightness: Option<f64>,
    pub notes: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct CalibrationRecord {
    pub record_id: String,
    pub workflow: Workflow,
    pub status: RecordStatus,
    /// RFC 3339, UTC.
    pub created_at: String,
    pub model: GazeModel,
    pub training: Option<TrainingSummary>,
    pub validation: ValidationReport,
    pub collections: Vec<CollectionSummary>,
    pub coverage: Option<PoseCoverage>,
    pub environment: Environment,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct SoftwareInfo {
    pub app_version: String,
    pub engine_version: Option<String>,
    pub engine_protocol: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Profile {
    /// Always [`crate::PROFILE_SCHEMA_ID`].
    pub schema: String,
    pub schema_version: u32,
    /// Random identifier; not derived from the person.
    pub profile_id: String,
    /// User-chosen label. Anonymous by design: no name is required.
    pub name: String,
    pub created_at: String,
    pub updated_at: String,
    pub software: SoftwareInfo,
    pub rig: RigConfig,
    pub display: DisplayCalibration,
    pub face_baseline: Option<FaceBaseline>,
    /// The model in use; None until a calibration was accepted.
    pub active: Option<CalibrationRecord>,
    /// Earlier and rejected records, newest first, bounded in length by the store.
    pub history: Vec<CalibrationRecord>,
}
