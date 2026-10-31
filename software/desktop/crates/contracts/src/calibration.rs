//! Calibration data: what targets to show, what was shown, what was learned and how well it
//! validates. The engine (Python) computes all of it; the core (Rust) orchestrates and stores.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::metric::{Metric, MetricSet, NormPoint};
use crate::tracking::PoseCoverage;

/// What a set of collected samples is used for. Validation data is never used to fit.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum Purpose {
    Fit,
    Validation,
}

/// Stationary target layouts.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "layout", rename_all = "snake_case")]
#[ts(export)]
pub enum StationaryLayout {
    /// Centre, the four edge midpoints and the four corners, inset by `margin`.
    CentreEdgesCorners { margin: f64 },
    /// A `cols` x `rows` grid inset by `margin`.
    Grid { cols: u32, rows: u32, margin: f64 },
    /// Points between the fit grid's points, for independent validation.
    ValidationOffsetGrid { cols: u32, rows: u32, margin: f64 },
    /// Explicit points.
    Points { points: Vec<NormPoint> },
}

/// Smooth-pursuit trajectories.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "trajectory", rename_all = "snake_case")]
#[ts(export)]
pub enum Trajectory {
    /// Archimedean spiral from the centre outwards to `margin` from the edges.
    Spiral { turns: f64, margin: f64 },
    /// Back-and-forth horizontal sweeps on `rows` rows, then vertical ones on `cols` columns.
    Sweeps { rows: u32, cols: u32, margin: f64 },
    /// Along the edges, through every corner.
    Perimeter { margin: f64 },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "method", rename_all = "snake_case")]
#[ts(export)]
pub enum PlanRequest {
    Stationary {
        purpose: Purpose,
        layout: StationaryLayout,
        /// Time after each target appears before samples count (saccade and settling).
        settle_ms: u32,
        /// Time the target stays after settling.
        dwell_ms: u32,
        /// Display aspect ratio (width / height), to keep spacing even on screen.
        aspect: f64,
    },
    Pursuit {
        purpose: Purpose,
        trajectory: Trajectory,
        /// Target speed in display heights per second. Comfortable pursuit is slow; about
        /// 0.15-0.3 at typical distances (provisional, to be tuned on hardware).
        speed: f64,
        /// The target rests at its start for this long before moving.
        lead_in_ms: u32,
        aspect: f64,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct StationaryTarget {
    pub index: u32,
    pub position: NormPoint,
}

/// A sample of a pursuit path. The presenter interpolates linearly between samples.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct PathSample {
    pub t_ms: f64,
    pub position: NormPoint,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "method", rename_all = "snake_case")]
#[ts(export)]
pub enum TargetPlanBody {
    Stationary {
        targets: Vec<StationaryTarget>,
        settle_ms: u32,
        dwell_ms: u32,
    },
    Pursuit {
        path: Vec<PathSample>,
        lead_in_ms: u32,
        trajectory: Trajectory,
    },
}

/// Targets for the UI to present, made by the engine.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct TargetPlan {
    pub plan_id: String,
    pub purpose: Purpose,
    pub duration_ms: f64,
    pub body: TargetPlanBody,
}

/// One presented frame: from `t_ns` on, the target was drawn at `position`.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct PresentedFrame {
    /// CLOCK_MONOTONIC nanoseconds (the same clock as camera frame timestamps).
    pub t_ns: i64,
    pub position: NormPoint,
    /// For stationary plans: the target's index.
    pub target_index: Option<u32>,
}

/// A span of time during which the plan was being shown (pauses split a presentation).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct TimeSpan {
    pub start_ns: i64,
    pub end_ns: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum PresentationClock {
    /// Timestamps were taken on CLOCK_MONOTONIC directly (simulated presenter).
    Monotonic,
    /// UI timestamps mapped to CLOCK_MONOTONIC by an offset measured at clock sync.
    UiMapped,
}

/// What was actually shown, reported by the presenter.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Presentation {
    pub plan_id: String,
    pub frames: Vec<PresentedFrame>,
    pub spans: Vec<TimeSpan>,
    /// False when the user skipped to the end.
    pub completed: bool,
    pub clock: PresentationClock,
    /// Uncertainty of the timestamps as presented-on-glass times, if estimated.
    pub clock_uncertainty_ms: Option<f64>,
}

/// Why samples were not used. Counts are of feature samples (one per camera frame).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct RejectionCounts {
    pub missing: u32,
    pub low_confidence: u32,
    pub blink: u32,
    pub unstable: u32,
    pub not_following: u32,
    pub settling: u32,
    pub outside_presentation: u32,
}

/// The result of aligning one presentation with the tracked features.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct CollectionSummary {
    pub plan_id: String,
    pub purpose: Purpose,
    pub samples_total: u32,
    pub samples_accepted: u32,
    pub rejected: RejectionCounts,
    /// Stationary: targets with enough accepted samples.
    pub targets_usable: Option<u32>,
    pub targets_total: Option<u32>,
    /// Pursuit: estimated delay from presentation to the eye features (display + eye +
    /// tracking latency).
    pub estimated_lag_ms: Metric,
    /// Pursuit: fraction of the presented time in which the eyes followed the target.
    pub following_fraction: Metric,
    pub warnings: Vec<String>,
}

/// A fitted gaze model. Its parameters belong to the engine that fitted it, which validates
/// them; the core stores them without interpreting them.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct GazeModel {
    /// e.g. `poly2-head-linear`.
    pub kind: String,
    pub kind_version: u32,
    /// The feature definition it was fitted on, e.g. `iris-in-eye/v1`.
    pub feature_set: String,
    pub engine_version: String,
    #[ts(type = "Record<string, unknown>")]
    #[schemars(with = "serde_json::Map<String, serde_json::Value>")]
    pub parameters: serde_json::Value,
}

/// Everything the engine needs to express errors in physical units. Computed by the core's
/// geometry from the display and its pose; the engine does not transform frames itself.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct MetricScale {
    pub width_px: u32,
    pub height_px: u32,
    /// Physical size of the visible image (after rotation), if known.
    pub width_mm: Option<f64>,
    pub height_mm: Option<f64>,
    /// The eyes' midpoint in the physical display frame (mm), if the screen pose and viewing
    /// distance are known.
    pub eye_position_mm: Option<[f64; 3]>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum ValidationSource {
    /// Targets that were not used for fitting: an accuracy estimate for these conditions.
    Independent,
    /// No independent data: nothing about real-world accuracy can be said.
    None,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct RegionError {
    pub col: u32,
    pub row: u32,
    pub samples: u32,
    pub median: MetricSet,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct AccuracyMetrics {
    pub median: MetricSet,
    pub rms: MetricSet,
    pub p90: MetricSet,
    /// Mean signed error, predicted minus target: + is right / down.
    pub bias_x: MetricSet,
    pub bias_y: MetricSet,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct SampleAcceptance {
    pub total: u32,
    pub accepted: u32,
    pub rejected: RejectionCounts,
    pub acceptance_rate: Metric,
}

/// Errors of a model against validation targets.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct ValidationReport {
    pub source: ValidationSource,
    pub targets: u32,
    pub samples: u32,
    /// Unavailable metrics carry the reason (e.g. `ValidationSource::None`).
    pub accuracy: Option<AccuracyMetrics>,
    /// Region grid of `region_cols` x `region_rows`, row-major; regions without validation
    /// samples are absent.
    pub region_cols: u32,
    pub region_rows: u32,
    pub regions: Vec<RegionError>,
    pub acceptance: SampleAcceptance,
    /// Delay between presentation and features, from pursuit data if there was any.
    pub latency_ms: Metric,
}

/// Fit diagnostics on the training data itself. Not an accuracy measurement.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct TrainingSummary {
    pub samples: u32,
    pub targets: u32,
    pub train_rms_px: Metric,
    /// Leave-one-target-out RMS over the fit targets (stationary data only).
    pub leave_one_out_rms_px: Metric,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct FitResult {
    pub model: GazeModel,
    pub training: TrainingSummary,
    pub validation: ValidationReport,
    pub coverage: Option<PoseCoverage>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum Verdict {
    /// The candidate is measurably better on the same validation data.
    Better,
    /// Not measurably different.
    Equivalent,
    /// The candidate is worse.
    Worse,
    /// Too little validation data to decide.
    Inconclusive,
}

/// The engine's comparison of a candidate model with the current one, on the same fresh
/// validation data.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct ModelComparison {
    pub verdict: Verdict,
    pub reason: String,
    pub current: ValidationReport,
    pub candidate: ValidationReport,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct RecalibrationResult {
    pub candidate: GazeModel,
    pub comparison: ModelComparison,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum TrustSource {
    /// The user explicitly confirmed looking at this point (e.g. a confirm-gaze key).
    ExplicitConfirmation,
    /// A validation target shown by the calibration UI.
    ValidationTarget,
}

/// An observation trusted enough to correct drift. Ordinary clicks are not trusted: the user
/// may click without looking at the target.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct TrustedObservation {
    pub t_ns: i64,
    pub display_stable_id: Option<String>,
    pub target: NormPoint,
    pub source: TrustSource,
}
