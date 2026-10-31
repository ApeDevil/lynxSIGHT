//! End-to-end workflows against the real `sight-engine` process on the simulated user.
//! Needs `uv` (or `LYNX_SIGHT_ENGINE`). Synthetic results; not a hardware measurement.

use lynx_sight_contracts::app::{Acceptance, Step};
use lynx_sight_contracts::calibration::Verdict;
use lynx_sight_contracts::engine::{SourceSpec, SyntheticScenario};
use lynx_sight_contracts::profile::{RecordStatus, Workflow};
use lynx_sight_profile::ProfileStore;
use lynx_sight_session::demo;
use lynx_sight_session::engine::{Engine, EngineCommand, EngineError};
use lynx_sight_session::workflow::{new_profile, CalibrationSession, SessionError};

fn synthetic(seed: u64) -> SourceSpec {
    SourceSpec::Synthetic {
        scenario: SyntheticScenario::default(),
        seed,
    }
}

#[test]
fn full_then_quick_recalibration_corrects_drift_and_keeps_history() {
    let dir = tempfile::tempdir().unwrap();
    let store = ProfileStore::new(dir.path());
    let (profile, outcomes) =
        demo::full_then_quick(&EngineCommand::from_env(), &store, 1, [0.02, -0.015]).unwrap();
    let [full, quick, again] = &outcomes[..] else {
        panic!()
    };
    assert!(full.installed && full.candidate.comparison.is_none());
    let px = |r: &lynx_sight_contracts::calibration::ValidationReport| {
        r.accuracy.as_ref().unwrap().median.px.value().unwrap()
    };
    assert!(px(&full.candidate.validation) < 80.0);
    let q = quick.candidate.comparison.as_ref().unwrap();
    assert_eq!(q.verdict, Verdict::Better, "{}", q.reason);
    assert!(px(&q.current) > 1.8 * px(&q.candidate));
    assert!(quick.installed);
    // Without further drift the correction is not better: the active model stays.
    let a = again.candidate.comparison.as_ref().unwrap();
    assert_ne!(a.verdict, Verdict::Better, "{}", a.reason);
    assert!(!again.installed);
    // The saved profile: corrected model active, the full one superseded, the last rejected.
    let loaded = store.load(&profile.profile_id).unwrap();
    assert_eq!(loaded.active.as_ref().unwrap().workflow, Workflow::Quick);
    let statuses: Vec<_> = loaded
        .history
        .iter()
        .map(|r| (r.workflow, r.status))
        .collect();
    assert_eq!(
        statuses,
        [
            (Workflow::Quick, RecordStatus::Rejected),
            (Workflow::Full, RecordStatus::Superseded)
        ]
    );
    assert!(loaded.face_baseline.is_some());
}

#[test]
fn synthetic_runs_are_reproducible() {
    let run = || {
        let dir = tempfile::tempdir().unwrap();
        let store = ProfileStore::new(dir.path());
        let p = new_profile("r", demo::simulated_display(), demo::synthetic_rig(), None);
        let (_, o) = demo::run(
            &EngineCommand::from_env(),
            &store,
            p,
            Workflow::Full,
            SyntheticScenario::default(),
            4,
            "full",
        )
        .unwrap();
        o.candidate.validation
    };
    assert_eq!(run(), run());
}

#[test]
fn steps_can_be_restarted_skipped_redone_and_need_the_right_plan() {
    let engine = Engine::start(&EngineCommand::from_env()).unwrap();
    let profile = new_profile("s", demo::simulated_display(), demo::synthetic_rig(), None);
    let mut s = CalibrationSession::start(engine, synthetic(2), profile, Workflow::Full).unwrap();
    let t = s.clock_origin_ns + 1_000_000_000;
    assert!(s.plan().is_err(), "baseline comes first");
    assert!(s.skip_step().is_err(), "baseline stages cannot be skipped");
    let mut t = t;
    for _ in 0..3 {
        let span = lynx_sight_contracts::calibration::TimeSpan {
            start_ns: t,
            end_ns: t + 3_000_000_000,
        };
        assert!(s.capture_baseline(span).unwrap().ok);
        t += 3_500_000_000;
    }
    assert!(s.view().baseline.is_some());
    let plan = s.plan().unwrap();
    let (mut presentation, _) = lynx_sight_session::presenter::simulate(&plan, t);
    presentation.plan_id = "plan-999".into();
    assert!(matches!(s.submit(presentation), Err(SessionError::Step(_))));
    s.restart_step();
    assert!(s.view().plan.is_none());
    s.skip_step().unwrap(); // skip the stationary targets
    s.skip_step().unwrap(); // and the spiral
    let after = s.simulate_until_review(t).unwrap();
    let view = s.view();
    assert!(view.steps[3].skipped && view.steps[4].skipped);
    assert!(matches!(view.steps.last().unwrap().step, Step::Review));
    let candidate = view.candidate.unwrap();
    assert!(
        candidate.fit.unwrap().training.targets == 0,
        "pursuit only: no stationary fit targets"
    );
    // Redo the skipped stationary step: everything after it is cleared.
    s.redo(3).unwrap();
    assert_eq!(s.view().current, 3);
    assert!(s.view().candidate.is_none());
    s.simulate_until_review(after).unwrap();
    assert!(s.view().candidate.unwrap().fit.unwrap().training.targets >= 7);
}

#[test]
fn quick_recalibration_needs_an_active_model_and_confirmation_is_enforced() {
    let dir = tempfile::tempdir().unwrap();
    let store = ProfileStore::new(dir.path());
    let profile = new_profile("q", demo::simulated_display(), demo::synthetic_rig(), None);
    let engine = Engine::start(&EngineCommand::from_env()).unwrap();
    let err = CalibrationSession::start(engine, synthetic(3), profile.clone(), Workflow::Quick)
        .err()
        .unwrap();
    assert!(err.to_string().contains("active calibration"));
    // A full calibration without validation data needs explicit confirmation.
    let engine = Engine::start(&EngineCommand::from_env()).unwrap();
    let mut s = CalibrationSession::start(engine, synthetic(3), profile, Workflow::Full).unwrap();
    let mut t = s.clock_origin_ns + 1_000_000_000;
    while let Some(step) = s.current_step().cloned() {
        match step {
            Step::Collect { label, .. } if label.starts_with("Validation") => {
                s.skip_step().unwrap()
            }
            Step::Review => break,
            _ => t = s.simulate_step(t).unwrap(),
        }
    }
    let c = s.view().candidate.unwrap();
    assert!(matches!(c.acceptance, Acceptance::ConfirmFirst { .. }));
    assert!(s.accept(&store, false).is_err());
    s.accept(&store, true).unwrap();
    assert!(store.load(&s.profile.profile_id).unwrap().active.is_some());
}

#[test]
fn a_missing_engine_is_reported_not_fatal() {
    let command = EngineCommand {
        program: "/nonexistent/sight-engine".into(),
        args: vec![],
    };
    assert!(matches!(
        Engine::start(&command),
        Err(EngineError::Unavailable { .. })
    ));
    let exits = EngineCommand {
        program: "sh".into(),
        args: vec!["-c".into(), "echo not-json".into()],
    };
    assert!(matches!(
        Engine::start(&exits),
        Err(EngineError::Protocol(_)) | Err(EngineError::Unavailable { .. })
    ));
    let quiet = EngineCommand {
        program: "sh".into(),
        args: vec!["-c".into(), "exit 3".into()],
    };
    assert!(matches!(
        Engine::start(&quiet),
        Err(EngineError::Unavailable { .. })
    ));
}
