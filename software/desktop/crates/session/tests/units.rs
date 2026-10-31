use lynx_sight_contracts::app::{Acceptance, CompatibilityStatus};
use lynx_sight_contracts::calibration::*;
use lynx_sight_contracts::display::DisplayLayout;
use lynx_sight_contracts::metric::*;
use lynx_sight_contracts::pointer::{IntentState, PointerAction, PointerMode};
use lynx_sight_contracts::tracking::*;
use lynx_sight_session::clock::{monotonic_ns, UiClock};
use lynx_sight_session::compatibility::{assess, Conditions};
use lynx_sight_session::pointer::{intent, GazeEstimate, Inputs, PointerPolicy};
use lynx_sight_session::{acceptance, demo, workflow};

fn set(px: f64) -> MetricSet {
    MetricSet {
        px: Metric::available(px),
        mm: Metric::unavailable("-"),
        deg: Metric::unavailable("-"),
    }
}

fn report(px: Option<f64>) -> ValidationReport {
    ValidationReport {
        source: if px.is_some() {
            ValidationSource::Independent
        } else {
            ValidationSource::None
        },
        targets: 6,
        samples: 100,
        accuracy: px.map(|v| AccuracyMetrics {
            median: set(v),
            rms: set(v),
            p90: set(v),
            bias_x: set(0.0),
            bias_y: set(0.0),
        }),
        region_cols: 3,
        region_rows: 3,
        regions: vec![],
        acceptance: SampleAcceptance {
            total: 100,
            accepted: 100,
            rejected: RejectionCounts::default(),
            acceptance_rate: Metric::available(1.0),
        },
        latency_ms: Metric::unavailable("-"),
    }
}

fn comparison(verdict: Verdict) -> ModelComparison {
    ModelComparison {
        verdict,
        reason: "test".into(),
        current: report(Some(40.0)),
        candidate: report(Some(30.0)),
    }
}

#[test]
fn monotonic_clock_advances_and_ui_mapping_takes_the_fastest_sample() {
    let a = monotonic_ns();
    assert!(monotonic_ns() >= a && a > 0);
    let clock = UiClock::from_samples(&[
        (1000.0, 5_001_000_000),
        (1010.0, 5_010_300_000),
        (1020.0, 5_020_100_000),
    ])
    .unwrap();
    assert_eq!(clock.offset_ns, 4_000_100_000);
    assert!((clock.uncertainty_ms - 0.9).abs() < 1e-9);
    assert_eq!(clock.to_monotonic(2000.0), 6_000_100_000);
    assert!(UiClock::from_samples(&[]).is_none());
}

#[test]
fn acceptance_never_replaces_silently() {
    assert_eq!(
        acceptance::decide(&report(Some(30.0)), None, false),
        Acceptance::Install
    );
    assert!(matches!(
        acceptance::decide(&report(None), None, false),
        Acceptance::ConfirmFirst { .. }
    ));
    assert_eq!(
        acceptance::decide(
            &report(Some(30.0)),
            Some(&comparison(Verdict::Better)),
            true
        ),
        Acceptance::Install
    );
    for v in [Verdict::Equivalent, Verdict::Worse, Verdict::Inconclusive] {
        assert!(
            matches!(
                acceptance::decide(&report(Some(30.0)), Some(&comparison(v)), true),
                Acceptance::ConfirmFirst { .. }
            ),
            "{v:?}"
        );
    }
    assert!(matches!(
        acceptance::decide(&report(Some(30.0)), None, true),
        Acceptance::ConfirmFirst { .. }
    ));
}

fn tracking(interocular: f64, yaw: f64) -> TrackingStatus {
    let eye = |eye| EyeStatus {
        eye,
        state: EyeState::Tracked,
        openness: Metric::available(0.28),
        confidence: Metric::available(0.9),
    };
    TrackingStatus {
        t_ns: 0,
        cameras: vec![CameraTracking {
            camera_id: "cam_left".into(),
            state: CameraState::Synthetic,
            fps: Metric::available(60.0),
            face_detected: true,
            face_confidence: Metric::available(0.9),
            eyes: vec![eye(EyeLabel::ImageLeft), eye(EyeLabel::ImageRight)],
            head_pose: Some(HeadPose {
                yaw_deg: yaw,
                pitch_deg: 0.0,
                roll_deg: 0.0,
                calibrated: false,
            }),
            interocular_px: Metric::available(interocular),
            face_centre_norm: Some([0.5, 0.45]),
            pipeline_latency_ms: Metric::available(10.0),
        }],
        guidance: vec![Guidance::Good],
        ready: true,
        mean_image_level: Metric::unavailable("synthetic"),
    }
}

fn calibrated_profile() -> lynx_sight_contracts::profile::Profile {
    let dir = tempfile::tempdir().unwrap();
    let store = lynx_sight_profile::ProfileStore::new(dir.path());
    let mut p = workflow::new_profile("t", demo::simulated_display(), demo::synthetic_rig(), None);
    let record = serde_json::from_str::<lynx_sight_contracts::profile::Profile>(include_str!(
        "../../../../../contracts/fixtures/profile-v1.json"
    ))
    .unwrap()
    .active
    .unwrap();
    lynx_sight_profile::history::install_active(&mut p, record);
    p.face_baseline = Some(FaceBaseline {
        stages: vec![],
        cameras: vec![CameraBaseline {
            camera_id: "cam_left".into(),
            interocular_px: Metric::available(180.0),
            interocular_iqr_px: Metric::available(2.0),
            openness: vec![],
            iris_in_eye: vec![],
            face_centre_norm: None,
        }],
        observed: coverage(),
        reliable: coverage(),
        features: vec![],
        inferred: InferredPhysical {
            interocular_mm: Metric::unavailable("-"),
            eye_distance_from_rig_mm: Metric::unavailable("-"),
        },
    });
    p.active.as_mut().unwrap().coverage = Some(PoseCoverage {
        yaw_deg: Some(Range {
            min: -8.0,
            max: 8.0,
        }),
        ..coverage()
    });
    store.save(&p).unwrap();
    p
}

fn coverage() -> PoseCoverage {
    PoseCoverage {
        pose_source: "synthetic".into(),
        yaw_deg: None,
        pitch_deg: None,
        roll_deg: None,
        face_x_norm: None,
        face_y_norm: None,
        scale_rel: None,
    }
}

#[test]
fn compatibility_separates_hard_and_soft_changes() {
    let p = calibrated_profile();
    let display = p.display.display.clone();
    let ok = tracking(185.0, 2.0);
    let now = |t| Conditions {
        display: &display,
        source: "synthetic",
        feature_set: "iris-in-eye/v1",
        tracking: t,
    };
    assert_eq!(
        assess(&p, &now(Some(&ok))).status,
        CompatibilityStatus::Compatible
    );
    let closer = tracking(240.0, 2.0);
    let c = assess(&p, &now(Some(&closer)));
    assert_eq!(c.status, CompatibilityStatus::Degraded);
    assert!(c.reasons[0].contains("distance"));
    let turned = tracking(180.0, 25.0);
    assert_eq!(
        assess(&p, &now(Some(&turned))).status,
        CompatibilityStatus::Degraded
    );
    assert_eq!(assess(&p, &now(None)).status, CompatibilityStatus::Unknown);
    let mut other = display.clone();
    other.id.stable = Some("edid:XYZ-0002-2".into());
    let c = assess(
        &p,
        &Conditions {
            display: &other,
            ..now(Some(&ok))
        },
    );
    assert_eq!(c.status, CompatibilityStatus::Incompatible);
    let c = assess(
        &p,
        &Conditions {
            feature_set: "pupil-offset/v1",
            ..now(Some(&ok))
        },
    );
    assert_eq!(c.status, CompatibilityStatus::Incompatible);
    let c = assess(
        &p,
        &Conditions {
            source: "cameras",
            ..now(Some(&ok))
        },
    );
    assert_eq!(c.status, CompatibilityStatus::Incompatible);
}

#[test]
fn pointer_intent_is_dry_and_conservative() {
    let cal = demo::simulated_display();
    let layout = DisplayLayout {
        displays: vec![cal.display.clone()],
        sources: vec![],
        warnings: vec![],
    };
    let gaze = GazeEstimate {
        t_ns: 1_000_000_000,
        display_stable_id: cal.display.id.stable.clone(),
        target: NormPoint { x: 0.25, y: 0.5 },
        confidence: Some(0.9),
    };
    let policy = PointerPolicy::default();
    let base = Inputs {
        now_ns: 1_050_000_000,
        gaze: Some(&gaze),
        last_manual_ns: None,
        activation_pressed: true,
        observed_cursor: None,
    };
    // Manual mode never acts, even on the activation key.
    assert_eq!(
        intent(PointerMode::Manual, &policy, &layout, &base).action,
        PointerAction::None
    );
    let assisted = intent(PointerMode::GazeAssisted, &policy, &layout, &base);
    assert_eq!(assisted.state, IntentState::Tracking);
    let PointerAction::Warp { to } = assisted.action else {
        panic!("expected a warp")
    };
    assert_eq!((to.x, to.y), (640.0, 720.0));
    // No key, no movement.
    let idle = Inputs {
        activation_pressed: false,
        ..base
    };
    assert_eq!(
        intent(PointerMode::GazeAssisted, &policy, &layout, &idle).action,
        PointerAction::None
    );
    let stale = Inputs {
        now_ns: 1_400_000_000,
        ..base
    };
    assert!(matches!(
        intent(PointerMode::GazeAssisted, &policy, &layout, &stale).state,
        IntentState::Stale { .. }
    ));
    let manual = Inputs {
        last_manual_ns: Some(1_000_000_000),
        ..base
    };
    let m = intent(PointerMode::HandsFree, &policy, &layout, &manual);
    assert_eq!(
        (m.state, m.action),
        (IntentState::ManualOverride, PointerAction::None)
    );
    let lost = Inputs { gaze: None, ..base };
    assert_eq!(
        intent(PointerMode::GazeAssisted, &policy, &layout, &lost).state,
        IntentState::Lost
    );
    let unsure = GazeEstimate {
        confidence: Some(0.2),
        ..gaze.clone()
    };
    let low = Inputs {
        gaze: Some(&unsure),
        ..base
    };
    assert_eq!(
        intent(PointerMode::GazeAssisted, &policy, &layout, &low).action,
        PointerAction::None
    );
}
