//! The synthetic demonstration: full calibration, then quick recalibration with and without
//! introduced drift, all on the simulated user and a simulated display. Used by
//! `sight-calibrate demo` and the integration tests.

use lynx_sight_contracts::app::{Acceptance, Candidate};
use lynx_sight_contracts::calibration::Verdict;
use lynx_sight_contracts::display::{
    DesktopRect, Display, DisplayCalibration, DisplayId, PhysicalSize, PixelSize, Rotation,
};
use lynx_sight_contracts::engine::{SourceSpec, SyntheticScenario};
use lynx_sight_contracts::metric::Provenance;
use lynx_sight_contracts::profile::{Profile, RigConfig, Workflow};
use lynx_sight_profile::ProfileStore;

use crate::engine::{Engine, EngineCommand};
use crate::workflow::{new_profile, CalibrationSession, Result};

/// A 27" 2560×1440 display under a monitor-top rig, with assumed geometry.
pub fn simulated_display() -> DisplayCalibration {
    let display = Display {
        id: DisplayId {
            stable: Some("edid:SIM-0001-1".into()),
            connector: Some("SIM-1".into()),
        },
        name: "simulated 27\" display".into(),
        desktop: DesktopRect {
            x: 0,
            y: 0,
            width: 2560,
            height: 1440,
        },
        mode: PixelSize {
            width: 2560,
            height: 1440,
        },
        refresh_hz: Some(60.0),
        scale_factor: 1.0,
        rotation: Rotation::Deg0,
        primary: true,
        physical: Some(PhysicalSize {
            width_mm: 597.0,
            height_mm: 336.0,
            provenance: Provenance::Assumed,
        }),
    };
    DisplayCalibration {
        screen_pose: lynx_sight_geometry::screen_pose_below_rig(&display, 30.0, 15.0),
        display,
        viewing_distance_mm: Some(600.0),
        viewing_distance_provenance: Some(Provenance::Assumed),
    }
}

pub fn synthetic_rig() -> RigConfig {
    RigConfig {
        source: "synthetic".into(),
        baseline_mm: Some(257.0),
        cameras: vec![],
    }
}

pub struct Outcome {
    pub label: String,
    pub candidate: Candidate,
    pub installed: bool,
}

/// Runs `workflow` on the simulated user to review, then installs the candidate if the policy
/// allows it directly, else declines it (keeping the active model).
pub fn run(
    command: &EngineCommand,
    store: &ProfileStore,
    profile: Profile,
    workflow: Workflow,
    scenario: SyntheticScenario,
    seed: u64,
    label: &str,
) -> Result<(Profile, Outcome)> {
    let engine = Engine::start(command)?;
    let mut session = CalibrationSession::start(
        engine,
        SourceSpec::Synthetic { scenario, seed },
        profile,
        workflow,
    )?;
    let start = session.clock_origin_ns + 1_000_000_000;
    session.simulate_until_review(start)?;
    let candidate = session.view().candidate.expect("review has a candidate");
    let installed = matches!(candidate.acceptance, Acceptance::Install);
    if installed {
        session.accept(store, false)?;
    } else {
        session.decline(store)?;
    }
    Ok((
        session.profile.clone(),
        Outcome {
            label: label.into(),
            candidate,
            installed,
        },
    ))
}

/// Full calibration, then quick recalibration after drift, then quick recalibration without
/// drift. Returns the saved profile and the three outcomes.
pub fn full_then_quick(
    command: &EngineCommand,
    store: &ProfileStore,
    seed: u64,
    drift: [f64; 2],
) -> Result<(Profile, Vec<Outcome>)> {
    let engine_version = Engine::start(command)?.engine_version.clone();
    let profile = new_profile(
        "synthetic demo",
        simulated_display(),
        synthetic_rig(),
        Some(engine_version),
    );
    let base = SyntheticScenario::default();
    let (profile, full) = run(
        command,
        store,
        profile,
        Workflow::Full,
        base.clone(),
        seed,
        "full calibration",
    )?;
    let drifted = SyntheticScenario {
        feature_drift: drift,
        ..base.clone()
    };
    let (profile, quick) = run(
        command,
        store,
        profile,
        Workflow::Quick,
        drifted.clone(),
        seed,
        "quick recalibration after drift",
    )?;
    let (profile, again) = run(
        command,
        store,
        profile,
        Workflow::Quick,
        drifted,
        seed,
        "quick recalibration, no further drift",
    )?;
    Ok((profile, vec![full, quick, again]))
}

pub fn describe(o: &Outcome) -> String {
    let median = |r: &lynx_sight_contracts::calibration::ValidationReport| {
        r.accuracy
            .as_ref()
            .and_then(|a| a.median.px.value())
            .map_or("n/a".into(), |v| format!("{v:.1} px"))
    };
    let deg = o
        .candidate
        .validation
        .accuracy
        .as_ref()
        .and_then(|a| a.median.deg.value())
        .map_or("n/a".into(), |v| format!("{v:.2}°"));
    let mut text = format!(
        "{}: validation median {} ({deg})",
        o.label,
        median(&o.candidate.validation)
    );
    if let Some(c) = &o.candidate.comparison {
        let verdict = match c.verdict {
            Verdict::Better => "better",
            Verdict::Equivalent => "equivalent",
            Verdict::Worse => "worse",
            Verdict::Inconclusive => "inconclusive",
        };
        text += &format!(", active model {} → {verdict}", median(&c.current));
    }
    text += if o.installed {
        ", installed"
    } else {
        ", declined (active model kept)"
    };
    text
}
