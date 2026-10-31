//! The desktop app's commands, driven the way the UI drives them (clock sync, UI-timed
//! presentations), against the real engine on the simulated user. Synthetic results only.

use lynx_sight_contracts::app::{
    DisplaySetup, SourceChoice, Step, UiFrame, UiPresentation, UiSpan,
};
use lynx_sight_contracts::metric::Provenance;
use lynx_sight_contracts::profile::Workflow;
use lynx_sight_geometry::discovery::{DisplayDiscovery, Facts, PlatformMonitor};
use lynx_sight_profile::ProfileStore;
use lynx_sight_session::app::AppCore;
use lynx_sight_session::engine::EngineCommand;
use lynx_sight_session::{demo, presenter};

/// One display, as `demo::simulated_display` describes it, whatever the machine has.
struct FixedDisplays;

impl DisplayDiscovery for FixedDisplays {
    fn facts(&self, _platform: &[PlatformMonitor]) -> Facts {
        Facts::default()
    }

    fn discover(
        &self,
        _platform: &[PlatformMonitor],
    ) -> lynx_sight_contracts::display::DisplayLayout {
        lynx_sight_contracts::display::DisplayLayout {
            displays: vec![demo::simulated_display().display],
            sources: vec!["test".into()],
            warnings: vec![],
        }
    }
}

fn core(dir: &std::path::Path) -> AppCore {
    AppCore::new(
        ProfileStore::new(dir),
        EngineCommand::from_env(),
        Box::new(FixedDisplays),
        vec![],
    )
}

const SETUP: DisplaySetup = DisplaySetup {
    display_index: 0,
    measured_width_mm: Some(600.0),
    measured_height_mm: Some(340.0),
    rig_above_screen_mm: Some(30.0),
    screen_behind_rig_mm: Some(15.0),
    viewing_distance_mm: Some(600.0),
};

#[test]
fn a_full_calibration_through_the_app_commands() {
    let dir = tempfile::tempdir().unwrap();
    let mut app = core(dir.path());
    let status = app.status();
    assert!(
        matches!(
            status.engine,
            lynx_sight_contracts::app::EngineState::Running { .. }
        ),
        "{:?}",
        status.engine
    );
    let profile = app.create_profile("ui test", &SETUP).unwrap();
    let source = SourceChoice::Synthetic {
        seed: 5,
        scenario: None,
    };
    assert!(
        app.start_session(&profile.profile_id, Workflow::Quick, &source)
            .is_err(),
        "no quick recalibration without a calibration"
    );
    let view = app
        .start_session(&profile.profile_id, Workflow::Full, &source)
        .unwrap();
    assert!(view.synthetic);

    // The UI's performance.now() is 0 at the engine's time origin plus one second.
    let origin = app.session_clock_origin().unwrap() + 1_000_000_000;
    for i in 0..10 {
        app.sync_clock_at(f64::from(i), origin + i64::from(i) * 1_000_000 + 200_000);
    }
    let ui_ms = |ns: i64| (ns - origin) as f64 / 1e6;
    let mut now = 0.0;
    loop {
        let view = app.session().unwrap();
        let Some(record) = view.steps.get(view.current as usize) else {
            break;
        };
        match record.step.clone() {
            Step::Baseline { stage } => {
                let r = app.capture_baseline(stage, now, now + 3000.0).unwrap();
                assert!(r.ok, "{}", r.message);
                now += 3500.0;
            }
            Step::Collect { .. } => {
                let plan = app.plan().unwrap();
                let start = origin + (now * 1e6) as i64;
                let (p, end) = presenter::simulate(&plan, start);
                let ui = UiPresentation {
                    plan_id: p.plan_id,
                    frames: p
                        .frames
                        .iter()
                        .map(|f| UiFrame {
                            t_ms: ui_ms(f.t_ns),
                            position: f.position,
                            target_index: f.target_index,
                        })
                        .collect(),
                    spans: p
                        .spans
                        .iter()
                        .map(|s| UiSpan {
                            start_ms: ui_ms(s.start_ns),
                            end_ms: ui_ms(s.end_ns),
                        })
                        .collect(),
                    completed: true,
                    background_brightness: 0.2,
                };
                app.submit(&ui).unwrap();
                now = ui_ms(end) + 500.0;
            }
            Step::Fit | Step::Recalibrate => {
                app.run_model_step().unwrap();
            }
            Step::Review => {
                let c = view.candidate.unwrap();
                let median = &c.validation.accuracy.as_ref().unwrap().median;
                assert!(median.px.value().unwrap() < 80.0);
                // Measured geometry: millimetres and degrees are available.
                assert!(median.mm.value().is_some() && median.deg.value().is_some());
                app.accept(false).unwrap();
            }
        }
    }
    app.end_session();
    let profiles = app.list_profiles().unwrap();
    assert_eq!(profiles.len(), 1);
    assert!(profiles[0].has_model);
    let saved = app.store.load(&profile.profile_id).unwrap();
    assert_eq!(saved.rig.source, "synthetic");
    assert_eq!(
        saved.display.display.physical.unwrap().provenance,
        Provenance::UserMeasured
    );
    assert_eq!(
        saved.active.unwrap().environment.background_brightness,
        Some(0.2)
    );
    // Same display and source: nothing hard against it, but without live tracking the soft
    // checks (distance, head pose) cannot run, so it stays unknown rather than "compatible".
    let compat = app.compatibility(&profile.profile_id, &source).unwrap();
    assert_eq!(
        compat.status,
        lynx_sight_contracts::app::CompatibilityStatus::Unknown,
        "{:?}",
        compat.reasons
    );
    let cameras = SourceChoice::Cameras {
        experiment_config: "exp.yaml".into(),
    };
    let compat = app.compatibility(&profile.profile_id, &cameras).unwrap();
    assert_eq!(
        compat.status,
        lynx_sight_contracts::app::CompatibilityStatus::Incompatible
    );
}

#[test]
fn commands_without_a_session_or_clock_are_refused() {
    let dir = tempfile::tempdir().unwrap();
    let mut app = core(dir.path());
    assert!(app.plan().is_err());
    assert!(app.tracking().is_err());
    assert!(app.session().is_none());
    let unmeasured = DisplaySetup {
        measured_width_mm: None,
        rig_above_screen_mm: None,
        ..SETUP
    };
    let p = app.create_profile("unmeasured", &unmeasured).unwrap();
    let saved = app.store.load(&p.profile_id).unwrap();
    // The simulated display's size is "assumed"; no measurement replaced it, no pose invented.
    assert_eq!(
        saved.display.display.physical.unwrap().provenance,
        Provenance::Assumed
    );
    assert!(saved.display.screen_pose.is_none());
    let bad = DisplaySetup {
        display_index: 3,
        ..SETUP
    };
    assert!(app.create_profile("x", &bad).is_err());
    let source = SourceChoice::Synthetic {
        seed: 1,
        scenario: None,
    };
    app.start_session(&p.profile_id, Workflow::Full, &source)
        .unwrap();
    assert!(
        app.capture_baseline(
            lynx_sight_contracts::tracking::BaselineStage::DetectStable,
            0.0,
            1.0
        )
        .is_err(),
        "no clock sync yet"
    );
    assert!(app.delete_profile(&p.profile_id).is_err(), "in use");
    app.end_session();
    app.delete_profile(&p.profile_id).unwrap();
}
