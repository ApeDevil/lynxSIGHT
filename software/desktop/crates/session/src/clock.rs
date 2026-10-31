//! The one clock every cross-process timestamp uses: CLOCK_MONOTONIC in nanoseconds, the clock
//! of V4L2 buffer timestamps and of Python's `time.monotonic_ns()`.

use rustix::time::{clock_gettime, ClockId};

pub fn monotonic_ns() -> i64 {
    let t = clock_gettime(ClockId::Monotonic);
    t.tv_sec * 1_000_000_000 + t.tv_nsec
}

/// Maps the UI's `performance.now()` milliseconds onto CLOCK_MONOTONIC.
///
/// Each sync sample pairs the UI time at sending with the core's monotonic time at receipt.
/// The transport delay only ever adds, so the smallest offset is the best estimate, and the
/// spread of the offsets bounds the uncertainty. Display latency (draw call to light) is not
/// covered; pursuit alignment estimates the total lag instead.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UiClock {
    pub offset_ns: i64,
    pub uncertainty_ms: f64,
}

impl UiClock {
    pub fn from_samples(samples: &[(f64, i64)]) -> Option<UiClock> {
        let offsets: Vec<i64> = samples
            .iter()
            .map(|(ui_ms, mono)| mono - (ui_ms * 1e6) as i64)
            .collect();
        let min = *offsets.iter().min()?;
        let max = *offsets.iter().max()?;
        Some(UiClock {
            offset_ns: min,
            uncertainty_ms: (max - min) as f64 / 1e6,
        })
    }

    pub fn to_monotonic(&self, ui_ms: f64) -> i64 {
        (ui_ms * 1e6) as i64 + self.offset_ns
    }
}

use lynx_sight_contracts::app::UiPresentation;
use lynx_sight_contracts::calibration::{
    Presentation, PresentationClock, PresentedFrame, TimeSpan,
};

/// The UI's presentation on CLOCK_MONOTONIC.
pub fn map_presentation(ui: &UiPresentation, clock: &UiClock) -> Presentation {
    Presentation {
        plan_id: ui.plan_id.clone(),
        frames: ui
            .frames
            .iter()
            .map(|f| PresentedFrame {
                t_ns: clock.to_monotonic(f.t_ms),
                position: f.position,
                target_index: f.target_index,
            })
            .collect(),
        spans: ui
            .spans
            .iter()
            .map(|s| TimeSpan {
                start_ns: clock.to_monotonic(s.start_ms),
                end_ns: clock.to_monotonic(s.end_ms),
            })
            .collect(),
        completed: ui.completed,
        clock: PresentationClock::UiMapped,
        clock_uncertainty_ms: Some(clock.uncertainty_ms),
    }
}
