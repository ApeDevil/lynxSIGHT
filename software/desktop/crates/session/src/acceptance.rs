//! When a candidate model may replace the active one.
//!
//! The engine judges *how* the candidate compares (on the same fresh validation data); this
//! policy decides what that means for the profile. A model never replaces the active one
//! silently unless it is measurably better, and the previous one is always kept in history.

use lynx_sight_contracts::app::Acceptance;
use lynx_sight_contracts::calibration::{
    ModelComparison, ValidationReport, ValidationSource, Verdict,
};

pub fn decide(
    validation: &ValidationReport,
    comparison: Option<&ModelComparison>,
    has_active: bool,
) -> Acceptance {
    if validation.source == ValidationSource::None || validation.accuracy.is_none() {
        return Acceptance::ConfirmFirst {
            reason: "no independent validation data: its accuracy is unknown".into(),
        };
    }
    match (has_active, comparison) {
        (false, _) => Acceptance::Install,
        (true, None) => Acceptance::ConfirmFirst {
            reason: "could not be compared with the active calibration".into(),
        },
        (true, Some(c)) => match c.verdict {
            Verdict::Better => Acceptance::Install,
            Verdict::Equivalent => Acceptance::ConfirmFirst {
                reason: format!(
                    "not measurably better than the active calibration ({})",
                    c.reason
                ),
            },
            Verdict::Worse => Acceptance::ConfirmFirst {
                reason: format!(
                    "worse than the active calibration ({}); keeping the active one is recommended",
                    c.reason
                ),
            },
            Verdict::Inconclusive => Acceptance::ConfirmFirst {
                reason: format!("comparison inconclusive: {}", c.reason),
            },
        },
    }
}
