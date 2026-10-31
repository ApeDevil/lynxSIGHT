//! Pointer intent: what gaze-assisted pointing would do, independent of how (or whether) it is
//! carried out. The only backend so far is a dry run that injects nothing.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::metric::NormPoint;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum PointerMode {
    /// Gaze is ignored; the physical pointer is in charge. The default.
    #[default]
    Manual,
    /// The pointer jumps near the gaze target only when a physical key asks for it.
    GazeAssisted,
    /// Research only: continuous gaze control. Never enabled by default.
    HandsFree,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "state", rename_all = "snake_case")]
#[ts(export)]
pub enum IntentState {
    Tracking,
    /// The newest gaze estimate is older than the staleness limit.
    Stale {
        age_ms: f64,
    },
    Lost,
    /// Manual input happened recently; gaze must not fight it.
    ManualOverride,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct DesktopPoint {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct PointerIntent {
    /// CLOCK_MONOTONIC time of the gaze estimate.
    pub t_ns: i64,
    pub mode: PointerMode,
    pub state: IntentState,
    pub display_stable_id: Option<String>,
    pub target: Option<NormPoint>,
    /// Where the target is in desktop coordinates, computed with the display layout.
    pub target_desktop: Option<DesktopPoint>,
    /// 0..1, or None when unknown.
    pub confidence: Option<f64>,
    /// The cursor position, only where the platform lets us read it (often not on Wayland).
    pub observed_cursor: Option<DesktopPoint>,
    /// What a real backend would do now.
    pub action: PointerAction,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[serde(tag = "action", rename_all = "snake_case")]
#[ts(export)]
pub enum PointerAction {
    None,
    /// Move the pointer to this desktop point (on an activation key in gaze-assisted mode).
    Warp {
        to: DesktopPoint,
    },
}
