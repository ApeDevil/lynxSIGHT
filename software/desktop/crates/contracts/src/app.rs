//! What the desktop core shows the UI (Tauri commands and their results). Versioned with the
//! application: core and UI are built together, so this is not a stored format.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::calibration::{
    CollectionSummary, FitResult, ModelComparison, PlanRequest, TargetPlan, ValidationReport,
};
use crate::display::DisplayLayout;
use crate::profile::Workflow;
use crate::tracking::{BaselineStage, BaselineStageResult, FaceBaseline};

/// Whether a profile's calibration still fits the current conditions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum CompatibilityStatus {
    /// Same display, cameras and features; tracking within the calibrated range.
    Compatible,
    /// Usable, but conditions moved (distance, pose): validate or quick-recalibrate.
    Degraded,
    /// Different display, mode, cameras or features: needs a full calibration.
    Incompatible,
    /// Not enough information (no tracking yet, no baseline).
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Compatibility {
    pub status: CompatibilityStatus,
    pub reasons: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[ts(export)]
pub enum Step {
    Baseline {
        stage: BaselineStage,
    },
    Collect {
        label: String,
        request: PlanRequest,
    },
    /// Full calibration: fit on the collected fit data, validate on the validation data.
    Fit,
    /// Quick recalibration: correct the active model with the collected data.
    Recalibrate,
    /// The user accepts or declines the candidate.
    Review,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct StepRecord {
    pub step: Step,
    pub done: bool,
    pub skipped: bool,
    pub baseline: Option<BaselineStageResult>,
    pub collection: Option<CollectionSummary>,
}

/// What would happen on accept, decided by the core's acceptance policy.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "decision", rename_all = "snake_case")]
#[ts(export)]
pub enum Acceptance {
    /// Better than the current model (or the first one, validated): installing is safe.
    Install,
    /// Installing needs the user's explicit confirmation; the reason says why.
    ConfirmFirst { reason: String },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Candidate {
    pub workflow: Workflow,
    pub fit: Option<FitResult>,
    pub validation: ValidationReport,
    /// Against the active model on the same validation data, when there is one.
    pub comparison: Option<ModelComparison>,
    pub acceptance: Acceptance,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct SessionView {
    pub workflow: Workflow,
    pub profile_id: String,
    pub synthetic: bool,
    pub feature_set: String,
    pub steps: Vec<StepRecord>,
    /// Index into `steps` of the step to do next; `steps.len()` when finished.
    pub current: u32,
    /// The plan of the current collect step, once requested.
    pub plan: Option<TargetPlan>,
    pub baseline: Option<FaceBaseline>,
    pub candidate: Option<Candidate>,
    pub message: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct ProfileSummary {
    pub profile_id: String,
    pub name: Option<String>,
    pub updated_at: Option<String>,
    pub display_name: Option<String>,
    pub has_model: bool,
    pub active_validation: Option<ValidationReport>,
    /// Set when the file could not be loaded (corrupt, newer schema, ...).
    pub problem: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct AppStatus {
    pub app_version: String,
    pub engine: EngineState,
    pub displays: DisplayLayout,
    pub profile_dir: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "state", rename_all = "snake_case")]
#[ts(export)]
pub enum EngineState {
    Running {
        engine_version: String,
        landmarks: bool,
    },
    Unavailable {
        reason: String,
    },
}

/// A frame as the UI drew it, timed with `performance.now()` (ms).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct UiFrame {
    pub t_ms: f64,
    pub position: crate::metric::NormPoint,
    pub target_index: Option<u32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct UiSpan {
    pub start_ms: f64,
    pub end_ms: f64,
}

/// What the UI's presenter reports; the core maps it onto CLOCK_MONOTONIC.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct UiPresentation {
    pub plan_id: String,
    pub frames: Vec<UiFrame>,
    pub spans: Vec<UiSpan>,
    pub completed: bool,
    pub background_brightness: f64,
}

/// The user's description of the display setup for a new profile. Physical values the
/// user leaves empty stay unknown (or EDID estimates for the size).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct DisplaySetup {
    /// Index into the discovered layout.
    pub display_index: u32,
    pub measured_width_mm: Option<f64>,
    pub measured_height_mm: Option<f64>,
    /// Rig origin above the active area's top edge, and screen plane behind the rig origin.
    pub rig_above_screen_mm: Option<f64>,
    pub screen_behind_rig_mm: Option<f64>,
    pub viewing_distance_mm: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[ts(export)]
pub enum SourceChoice {
    Synthetic {
        seed: u64,
        scenario: Option<crate::engine::SyntheticScenario>,
    },
    Cameras {
        experiment_config: String,
    },
}
