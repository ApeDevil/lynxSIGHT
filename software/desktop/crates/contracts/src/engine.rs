//! The engine protocol: line-delimited JSON over the engine process's stdin/stdout.
//!
//! Every line is one [`Envelope`]. The core sends requests with increasing `id`s; the engine
//! answers each with exactly one response carrying the same `id`, in order. The first request
//! is `hello`; the engine refuses every other protocol version. Diagnostics go to the engine's
//! stderr, never stdout.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::calibration::{
    CollectionSummary, FitResult, GazeModel, MetricScale, ModelComparison, PlanRequest,
    Presentation, RecalibrationResult, TargetPlan, TimeSpan, TrustedObservation, ValidationReport,
};
use crate::metric::NormPoint;
use crate::tracking::{BaselineStage, BaselineStageResult, EyeLabel, FaceBaseline, TrackingStatus};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct Envelope<T> {
    pub protocol: u32,
    pub id: u64,
    #[serde(flatten)]
    pub body: T,
}

/// A deterministic simulated user and camera pair, for running every workflow without
/// hardware. Synthetic results say nothing about real tracking accuracy.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct SyntheticScenario {
    pub cameras: u32,
    pub fps: f64,
    /// Standard deviation of the iris-in-eye features (eye-width units).
    pub feature_noise: f64,
    /// Mean time between blinks; 0 disables blinks.
    pub blink_interval_s: f64,
    pub blink_duration_ms: f64,
    /// Rate and length of intervals in which one eye is not found.
    pub eye_loss_per_min: f64,
    pub eye_loss_duration_ms: f64,
    /// Presentation-to-photon delay not covered by the presentation timestamps.
    pub display_latency_ms: f64,
    /// Smooth-pursuit lag of the simulated eye behind the target.
    pub pursuit_lag_ms: f64,
    /// Fraction of pursuit time in which the simulated user looks elsewhere.
    pub pursuit_lapse_fraction: f64,
    /// The simulated user looks this far from every target (a systematic gaze offset).
    pub gaze_offset: NormPoint,
    /// Features shift by this much (eye-width units), as if the cameras had moved since
    /// calibration: drift that recalibration must correct.
    pub feature_drift: [f64; 2],
    /// Head movement: face-centre translation amplitude (normalized image units) and yaw /
    /// pitch amplitude (degrees), with period.
    pub head_translation: f64,
    pub head_rotation_deg: f64,
    pub head_period_s: f64,
    /// Camera dropouts, relative to `open_source`.
    pub disconnects: Vec<SyntheticDisconnect>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct SyntheticDisconnect {
    pub camera_id: String,
    pub after_ms: f64,
    pub duration_ms: f64,
}

impl Default for SyntheticScenario {
    /// A cooperative user with realistic imperfections.
    fn default() -> Self {
        SyntheticScenario {
            cameras: 2,
            fps: 60.0,
            feature_noise: 0.004,
            blink_interval_s: 4.0,
            blink_duration_ms: 150.0,
            eye_loss_per_min: 2.0,
            eye_loss_duration_ms: 300.0,
            display_latency_ms: 20.0,
            pursuit_lag_ms: 60.0,
            pursuit_lapse_fraction: 0.1,
            gaze_offset: NormPoint { x: 0.0, y: 0.0 },
            feature_drift: [0.0, 0.0],
            head_translation: 0.02,
            head_rotation_deg: 4.0,
            head_period_s: 7.0,
            disconnects: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "kind", rename_all = "snake_case")]
#[ts(export)]
pub enum SourceSpec {
    Synthetic {
        scenario: SyntheticScenario,
        seed: u64,
    },
    /// Real cameras as described by a `sight-diag` experiment config (camera device paths,
    /// capture mode, processing settings).
    Cameras { experiment_config: String },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "snake_case")]
#[ts(export)]
pub enum Request {
    Hello {
        client: String,
    },
    OpenSource {
        source: SourceSpec,
    },
    CloseSource,
    TrackingStatus,
    CaptureBaselineStage {
        stage: BaselineStage,
        span: TimeSpan,
    },
    FinishBaseline,
    Plan {
        request: PlanRequest,
    },
    SubmitPresentation {
        presentation: Presentation,
    },
    Fit {
        fit_plans: Vec<String>,
        validation_plans: Vec<String>,
        scale: MetricScale,
    },
    Evaluate {
        model: GazeModel,
        validation_plans: Vec<String>,
        scale: MetricScale,
    },
    /// Quick recalibration: correct `current` with a few new observations.
    Recalibrate {
        current: GazeModel,
        fit_plans: Vec<String>,
        validation_plans: Vec<String>,
        scale: MetricScale,
    },
    Compare {
        current: GazeModel,
        candidate: GazeModel,
        validation_plans: Vec<String>,
        scale: MetricScale,
    },
    /// Incremental correction from trusted observations (interface for future drift
    /// correction; the result is a candidate that must still win a `compare`).
    ProposeCorrection {
        current: GazeModel,
        observations: Vec<TrustedObservation>,
    },
    Shutdown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum ErrorCode {
    ProtocolMismatch,
    InvalidRequest,
    NoSource,
    SourceFailed,
    UnknownPlan,
    InsufficientData,
    ModelIncompatible,
    Internal,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Capabilities {
    pub cameras: bool,
    pub landmarks: bool,
    pub feature_sets: Vec<String>,
    pub model_kinds: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct CorrectionProposal {
    pub candidate: Option<GazeModel>,
    pub observations_used: u32,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct OpenedCamera {
    pub camera_id: String,
    pub description: String,
    pub eyes: Vec<EyeLabel>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "snake_case")]
#[ts(export)]
pub enum Response {
    Hello {
        engine_version: String,
        capabilities: Capabilities,
    },
    SourceOpened {
        cameras: Vec<OpenedCamera>,
        synthetic: bool,
        /// The engine's time origin (CLOCK_MONOTONIC): synthetic events are relative to it.
        clock_origin_ns: i64,
        /// The feature definition this source delivers, e.g. `iris-in-eye/v1`.
        feature_set: String,
    },
    TrackingStatus {
        status: TrackingStatus,
    },
    BaselineStage {
        result: BaselineStageResult,
    },
    Baseline {
        baseline: FaceBaseline,
    },
    Plan {
        plan: TargetPlan,
    },
    Collection {
        summary: CollectionSummary,
    },
    Fit {
        result: FitResult,
    },
    Validation {
        report: ValidationReport,
    },
    Recalibration {
        result: RecalibrationResult,
    },
    Comparison {
        comparison: ModelComparison,
    },
    CorrectionProposal {
        proposal: CorrectionProposal,
    },
    Ok,
    Error {
        code: ErrorCode,
        message: String,
    },
}
