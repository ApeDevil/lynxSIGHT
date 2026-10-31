//! Tracking quality (monitored continuously) and the personal face/eye baseline.
//!
//! Everything here is either an **image measurement** (pixels, ratios of pixel distances,
//! uncalibrated pose angles) or explicitly marked as an inferred physical quantity. Physical
//! quantities are unavailable until the cameras are calibrated.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::metric::{Metric, Range};

/// Which eye, named by its position in the camera image (`image_left` has the smaller x), not
/// by anatomy: the cameras face the user, so the image-left eye is the user's right eye.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum EyeLabel {
    ImageLeft,
    ImageRight,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum EyeState {
    /// Iris found inside an open eye with sufficient confidence.
    Tracked,
    /// The eye is closed or nearly closed.
    Closed,
    /// The face was found but this eye was not (turned away, occluded, out of frame).
    Occluded,
    /// No face, so no eye either.
    NoFace,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct EyeStatus {
    pub eye: EyeLabel,
    pub state: EyeState,
    /// Lid opening divided by eye width (image ratio).
    pub openness: Metric,
    /// Iris/pupil localisation confidence, 0..1, from the detector.
    pub confidence: Metric,
}

/// Head pose angles as estimated from the image. Uncalibrated: the landmark model assumes a
/// canonical face and a nominal camera, so the angles are indicative.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct HeadPose {
    pub yaw_deg: f64,
    pub pitch_deg: f64,
    pub roll_deg: f64,
    pub calibrated: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum Guidance {
    FaceNotFound,
    MoveLeft,
    MoveRight,
    MoveUp,
    MoveDown,
    MoveCloser,
    MoveBack,
    TurnTowardScreen,
    OpenEyes,
    HoldStill,
    Good,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum CameraState {
    Streaming,
    Starting,
    Disconnected,
    /// The synthetic source: no camera involved.
    Synthetic,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct CameraTracking {
    pub camera_id: String,
    pub state: CameraState,
    pub fps: Metric,
    pub face_detected: bool,
    pub face_confidence: Metric,
    pub eyes: Vec<EyeStatus>,
    pub head_pose: Option<HeadPose>,
    /// Inter-eye distance in pixels (image measurement).
    pub interocular_px: Metric,
    /// Face centre / image size, 0..1.
    pub face_centre_norm: Option<[f64; 2]>,
    /// Capture-to-feature latency of the newest result.
    pub pipeline_latency_ms: Metric,
}

/// Tracking quality right now. This is not calibration accuracy: it says whether features
/// can be measured, not whether the gaze estimate is right.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct TrackingStatus {
    /// CLOCK_MONOTONIC time of the status.
    pub t_ns: i64,
    pub cameras: Vec<CameraTracking>,
    /// Ordered, most important first; `[Good]` when nothing needs to change.
    pub guidance: Vec<Guidance>,
    /// True when at least one camera tracks both eyes.
    pub ready: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum BaselineStage {
    /// Hold still facing the screen until a stable face and both eyes are seen.
    DetectStable,
    /// Neutral frontal reference: look at the screen centre.
    Neutral,
    /// Slowly turn and move the head within a comfortable range while looking at the centre.
    PoseRange,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct BaselineStageResult {
    pub stage: BaselineStage,
    pub samples: u32,
    pub accepted: u32,
    pub ok: bool,
    pub message: String,
}

/// Image-space reference values of one camera in the neutral frontal pose.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct CameraBaseline {
    pub camera_id: String,
    pub interocular_px: Metric,
    /// Interquartile range of `interocular_px`, a stability indicator.
    pub interocular_iqr_px: Metric,
    /// Per eye: openness (lid opening / eye width) in the neutral pose.
    pub openness: Vec<EyeValue>,
    /// Per eye: iris position within the eye (eye-width units, origin at the corner midpoint).
    pub iris_in_eye: Vec<EyePoint>,
    pub face_centre_norm: Option<[f64; 2]>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct EyeValue {
    pub eye: EyeLabel,
    pub value: Metric,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct EyePoint {
    pub eye: EyeLabel,
    pub x: f64,
    pub y: f64,
}

/// The range of head poses and positions observed, and the part of it with reliable tracking
/// (both eyes tracked in at least one camera).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct PoseCoverage {
    /// `"landmarks-uncalibrated"` (MediaPipe pose angles), `"eye-line-roll"` (roll only, from
    /// the eye landmarks) or `"synthetic"`.
    pub pose_source: String,
    pub yaw_deg: Option<Range>,
    pub pitch_deg: Option<Range>,
    pub roll_deg: Option<Range>,
    /// Face centre in normalized image coordinates.
    pub face_x_norm: Option<Range>,
    pub face_y_norm: Option<Range>,
    /// Interocular distance relative to the neutral one: a proxy for distance changes.
    pub scale_rel: Option<Range>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct FeatureValidity {
    pub feature: String,
    pub valid: bool,
    pub reason: String,
}

/// Physical quantities inferred from the baseline. Unavailable until camera geometry is
/// calibrated; never filled from nominal guesses.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct InferredPhysical {
    pub interocular_mm: Metric,
    pub eye_distance_from_rig_mm: Metric,
}

/// A user's personal face/eye reference, saved with the profile. Contains derived numbers
/// only: no images, no landmark meshes. Not an identity: nothing here is used to recognise
/// a person.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct FaceBaseline {
    pub stages: Vec<BaselineStageResult>,
    pub cameras: Vec<CameraBaseline>,
    pub observed: PoseCoverage,
    pub reliable: PoseCoverage,
    pub features: Vec<FeatureValidity>,
    pub inferred: InferredPhysical,
}
