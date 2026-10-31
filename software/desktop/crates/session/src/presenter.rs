//! A presenter without a screen, for headless runs and tests: it "shows" a plan by reporting
//! the plan's own positions at the times they are due. Real presentation happens in the UI,
//! which reports what it actually drew in the same `Presentation` form.

use lynx_sight_contracts::calibration::{
    Presentation, PresentationClock, PresentedFrame, TargetPlan, TargetPlanBody, TimeSpan,
};

/// The presentation of `plan` starting at `start_ns` (CLOCK_MONOTONIC or a simulated time
/// base relative to the engine's clock origin). Returns it and the time it ends.
pub fn simulate(plan: &TargetPlan, start_ns: i64) -> (Presentation, i64) {
    let mut frames = Vec::new();
    match &plan.body {
        TargetPlanBody::Stationary {
            targets,
            settle_ms,
            dwell_ms,
        } => {
            let per_ns = i64::from(settle_ms + dwell_ms) * 1_000_000;
            for (i, t) in targets.iter().enumerate() {
                frames.push(PresentedFrame {
                    t_ns: start_ns + i as i64 * per_ns,
                    position: t.position,
                    target_index: Some(t.index),
                });
            }
        }
        TargetPlanBody::Pursuit { path, .. } => {
            for s in path {
                frames.push(PresentedFrame {
                    t_ns: start_ns + (s.t_ms * 1e6) as i64,
                    position: s.position,
                    target_index: None,
                });
            }
        }
    }
    let end_ns = start_ns + (plan.duration_ms * 1e6) as i64;
    let presentation = Presentation {
        plan_id: plan.plan_id.clone(),
        frames,
        spans: vec![TimeSpan { start_ns, end_ns }],
        completed: true,
        clock: PresentationClock::Monotonic,
        clock_uncertainty_ms: Some(0.0),
    };
    (presentation, end_ns)
}
