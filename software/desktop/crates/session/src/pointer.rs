//! Pointer intent and the dry-run backend. No pointer is moved: the backend records what a
//! real one would do, for visualisation. Gaze never clicks.
//!
//! Policy (all modes default off except manual):
//! * `Manual`: no action, ever.
//! * `GazeAssisted`: a warp to the gaze target only when the user presses the activation key,
//!   only with a fresh, confident estimate, and never within the manual-override window.
//! * `HandsFree`: research only; behaves like `GazeAssisted` in this backend.

use lynx_sight_contracts::display::DisplayLayout;
use lynx_sight_contracts::metric::NormPoint;
use lynx_sight_contracts::pointer::{IntentState, PointerAction, PointerIntent, PointerMode};

#[derive(Debug, Clone, Copy)]
pub struct PointerPolicy {
    pub stale_after_ms: f64,
    pub manual_override_ms: f64,
    pub min_confidence: f64,
}

impl Default for PointerPolicy {
    fn default() -> Self {
        PointerPolicy {
            stale_after_ms: 150.0,
            manual_override_ms: 500.0,
            min_confidence: 0.6,
        }
    }
}

/// A gaze estimate as the tracking side delivers it.
#[derive(Debug, Clone)]
pub struct GazeEstimate {
    pub t_ns: i64,
    pub display_stable_id: Option<String>,
    pub target: NormPoint,
    pub confidence: Option<f64>,
}

pub struct Inputs<'a> {
    pub now_ns: i64,
    pub gaze: Option<&'a GazeEstimate>,
    pub last_manual_ns: Option<i64>,
    pub activation_pressed: bool,
    pub observed_cursor: Option<lynx_sight_contracts::pointer::DesktopPoint>,
}

pub fn intent(
    mode: PointerMode,
    policy: &PointerPolicy,
    layout: &DisplayLayout,
    inputs: &Inputs,
) -> PointerIntent {
    let manual_recent = inputs
        .last_manual_ns
        .is_some_and(|t| (inputs.now_ns - t) as f64 / 1e6 < policy.manual_override_ms);
    let state = match inputs.gaze {
        _ if manual_recent => IntentState::ManualOverride,
        None => IntentState::Lost,
        Some(g) => {
            let age_ms = (inputs.now_ns - g.t_ns) as f64 / 1e6;
            if age_ms > policy.stale_after_ms {
                IntentState::Stale { age_ms }
            } else {
                IntentState::Tracking
            }
        }
    };
    let display = inputs.gaze.and_then(|g| {
        layout
            .displays
            .iter()
            .find(|d| d.id.stable.is_some() && d.id.stable == g.display_stable_id)
    });
    let target_desktop = inputs
        .gaze
        .zip(display)
        .map(|(g, d)| lynx_sight_geometry::norm_to_desktop(d, g.target));
    let confident = inputs
        .gaze
        .and_then(|g| g.confidence)
        .is_some_and(|c| c >= policy.min_confidence);
    let action = match (mode, state, target_desktop) {
        (PointerMode::GazeAssisted | PointerMode::HandsFree, IntentState::Tracking, Some(to))
            if inputs.activation_pressed && confident =>
        {
            PointerAction::Warp { to }
        }
        _ => PointerAction::None,
    };
    PointerIntent {
        t_ns: inputs.gaze.map_or(inputs.now_ns, |g| g.t_ns),
        mode,
        state,
        display_stable_id: inputs.gaze.and_then(|g| g.display_stable_id.clone()),
        target: inputs.gaze.map(|g| g.target),
        target_desktop,
        confidence: inputs.gaze.and_then(|g| g.confidence),
        observed_cursor: inputs.observed_cursor,
        action,
    }
}

/// Records intents instead of acting on them.
#[derive(Debug, Default)]
pub struct DryRunBackend {
    pub log: Vec<PointerIntent>,
}

impl DryRunBackend {
    pub fn apply(&mut self, intent: PointerIntent) {
        self.log.push(intent);
    }
}
