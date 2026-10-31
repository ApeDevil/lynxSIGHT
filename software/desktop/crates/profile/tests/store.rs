use lynx_sight_contracts::calibration::*;
use lynx_sight_contracts::display::*;
use lynx_sight_contracts::metric::*;
use lynx_sight_contracts::profile::*;
use lynx_sight_contracts::{PROFILE_SCHEMA_ID, PROFILE_SCHEMA_VERSION};
use lynx_sight_profile::migrate::{migrate_with, MigrationError};
use lynx_sight_profile::{history, new_id, now_rfc3339, ProfileError, ProfileStore};

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../../contracts/fixtures/profile-v1.json"
);

fn unavailable() -> MetricSet {
    MetricSet {
        px: Metric::unavailable("test"),
        mm: Metric::unavailable("test"),
        deg: Metric::unavailable("test"),
    }
}

fn record(px: f64) -> CalibrationRecord {
    let set = MetricSet {
        px: Metric::available(px),
        ..unavailable()
    };
    CalibrationRecord {
        record_id: new_id(),
        workflow: Workflow::Full,
        status: RecordStatus::Active,
        created_at: now_rfc3339(),
        model: GazeModel {
            kind: "poly2-head-linear".into(),
            kind_version: 1,
            feature_set: "iris-in-eye/v1".into(),
            engine_version: "0.2.0".into(),
            parameters: serde_json::json!({"coefficients": [[1.0, 0.0]]}),
        },
        training: None,
        validation: ValidationReport {
            source: ValidationSource::Independent,
            targets: 5,
            samples: 300,
            accuracy: Some(AccuracyMetrics {
                median: set.clone(),
                rms: set.clone(),
                p90: set.clone(),
                bias_x: unavailable(),
                bias_y: unavailable(),
            }),
            region_cols: 3,
            region_rows: 3,
            regions: vec![],
            acceptance: SampleAcceptance {
                total: 400,
                accepted: 300,
                rejected: RejectionCounts::default(),
                acceptance_rate: Metric::available(0.75),
            },
            latency_ms: Metric::unavailable("no pursuit data"),
        },
        collections: vec![],
        coverage: None,
        environment: Environment {
            camera_modes: vec!["synthetic".into()],
            mean_image_level: Metric::unavailable("synthetic"),
            background_brightness: Some(0.2),
            notes: String::new(),
        },
    }
}

fn profile() -> Profile {
    let now = now_rfc3339();
    Profile {
        schema: PROFILE_SCHEMA_ID.into(),
        schema_version: PROFILE_SCHEMA_VERSION,
        profile_id: new_id(),
        name: "desk".into(),
        created_at: now.clone(),
        updated_at: now,
        software: SoftwareInfo {
            app_version: "0.1.0".into(),
            engine_version: Some("0.2.0".into()),
            engine_protocol: 1,
        },
        rig: RigConfig {
            source: "synthetic".into(),
            baseline_mm: Some(257.0),
            cameras: vec![],
        },
        display: DisplayCalibration {
            display: Display {
                id: DisplayId {
                    stable: Some("edid:DEL-0002-9".into()),
                    connector: Some("DP-1".into()),
                },
                name: "U2720Q on DP-1".into(),
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
                    provenance: Provenance::Edid,
                }),
            },
            screen_pose: None,
            viewing_distance_mm: Some(600.0),
            viewing_distance_provenance: Some(Provenance::Assumed),
        },
        face_baseline: None,
        active: None,
        history: vec![],
    }
}

#[test]
fn save_and_load_round_trip_atomically() {
    let dir = tempfile::tempdir().unwrap();
    let store = ProfileStore::new(dir.path().join("profiles"));
    let mut p = profile();
    store.save(&p).unwrap();
    assert_eq!(store.load(&p.profile_id).unwrap(), p);
    p.name = "desk 2".into();
    store.save(&p).unwrap();
    assert_eq!(store.load(&p.profile_id).unwrap().name, "desk 2");
    let names: Vec<_> = std::fs::read_dir(store.dir())
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    assert!(
        names.iter().all(|n| !n.ends_with(".tmp")),
        "no temporary files left: {names:?}"
    );
    assert!(names.contains(&format!("{}.json.bak", p.profile_id)));
    let listed = store.list().unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].name.as_deref(), Some("desk 2"));
    store.delete(&p.profile_id).unwrap();
    assert!(matches!(
        store.load(&p.profile_id),
        Err(ProfileError::NotFound(_))
    ));
}

#[test]
fn invalid_profiles_are_not_saved() {
    let dir = tempfile::tempdir().unwrap();
    let store = ProfileStore::new(dir.path());
    let mut p = profile();
    p.name = " ".into();
    p.display.display.scale_factor = 0.0;
    let Err(ProfileError::Invalid(problems)) = store.save(&p) else {
        panic!()
    };
    assert_eq!(problems.len(), 2);
    assert!(store.list().unwrap().is_empty());
}

#[test]
fn broken_newer_and_foreign_files_are_listed_with_their_problem_and_left_alone() {
    let dir = tempfile::tempdir().unwrap();
    let store = ProfileStore::new(dir.path());
    let good = profile();
    store.save(&good).unwrap();
    let mut newer = serde_json::to_value(profile()).unwrap();
    newer["schema_version"] = 99.into();
    let newer_id = newer["profile_id"].as_str().unwrap().to_string();
    let newer_text = newer.to_string();
    std::fs::write(dir.path().join(format!("{newer_id}.json")), &newer_text).unwrap();
    let torn_id = new_id();
    std::fs::write(
        dir.path().join(format!("{torn_id}.json")),
        "{\"schema\": \"lynx-sight/pro",
    )
    .unwrap();
    std::fs::write(dir.path().join("notes.json"), "{}").unwrap();

    let entries = store.list().unwrap();
    assert_eq!(entries.len(), 3);
    let problem = |id: &str| {
        entries
            .iter()
            .find(|e| e.profile_id == id)
            .unwrap()
            .problem
            .clone()
    };
    assert_eq!(problem(&good.profile_id), None);
    assert!(problem(&newer_id).unwrap().contains("newer"));
    assert!(problem(&torn_id).unwrap().contains("JSON"));
    assert_eq!(
        std::fs::read_to_string(dir.path().join(format!("{newer_id}.json"))).unwrap(),
        newer_text
    );
}

#[test]
fn stale_or_inconsistent_profiles_fail_validation() {
    let mut p = profile();
    let mut r = record(30.0);
    r.status = RecordStatus::Rejected;
    p.active = Some(r);
    let text = serde_json::to_string(&p).unwrap();
    let Err(ProfileError::Invalid(problems)) = lynx_sight_profile::store::parse(&text) else {
        panic!()
    };
    assert!(problems[0].contains("active"));
    let mut v = serde_json::to_value(profile()).unwrap();
    v["display"] = serde_json::json!({"display": "DP-1"});
    assert!(matches!(
        lynx_sight_profile::store::parse(&v.to_string()),
        Err(ProfileError::Schema(_))
    ));
}

#[test]
fn migration_applies_steps_in_order_and_refuses_newer_or_foreign() {
    fn v1_to_v2(mut v: serde_json::Value) -> Result<serde_json::Value, String> {
        v["added_in_v2"] = true.into();
        Ok(v)
    }
    fn v2_to_v3(v: serde_json::Value) -> Result<serde_json::Value, String> {
        if v["added_in_v2"] == true {
            Ok(v)
        } else {
            Err("v2 field missing".into())
        }
    }
    let v1 = serde_json::json!({"schema": PROFILE_SCHEMA_ID, "schema_version": 1});
    let (out, from) = migrate_with(v1.clone(), &[v1_to_v2, v2_to_v3], 3).unwrap();
    assert_eq!(
        (
            from,
            out["schema_version"].as_u64(),
            out["added_in_v2"].as_bool()
        ),
        (1, Some(3), Some(true))
    );
    assert!(matches!(
        migrate_with(v1.clone(), &[v1_to_v2], 3),
        Err(MigrationError::Failed { from: 2, .. })
    ));
    assert!(matches!(
        migrate_with(v1, &[], 0),
        Err(MigrationError::Newer {
            found: 1,
            supported: 0
        })
    ));
    let other = serde_json::json!({"schema": "lynx-sight/experiment/v1"});
    assert!(matches!(
        migrate_with(other, &[], 1),
        Err(MigrationError::NotAProfile(_))
    ));
}

#[test]
fn installing_a_record_keeps_the_previous_one() {
    let mut p = profile();
    let first = record(40.0);
    let first_id = first.record_id.clone();
    history::install_active(&mut p, first);
    let second = record(30.0);
    history::install_active(&mut p, second);
    assert_eq!(p.history.len(), 1);
    assert_eq!(p.history[0].record_id, first_id);
    assert_eq!(p.history[0].status, RecordStatus::Superseded);
    history::add_rejected(&mut p, record(80.0));
    assert_eq!(p.history[0].status, RecordStatus::Rejected);
    assert!(history::restore(&mut p, &first_id));
    assert_eq!(p.active.as_ref().unwrap().record_id, first_id);
    assert!(lynx_sight_profile::validate::problems(&p).is_empty());
    for _ in 0..30 {
        history::add_rejected(&mut p, record(90.0));
    }
    assert_eq!(p.history.len(), lynx_sight_profile::validate::MAX_HISTORY);
}

/// A stored v1 profile must stay loadable by every later version of the software. The fixture
/// is also validated against the JSON Schema by the Python tests. Recreate (only when the
/// schema version changes) with `UPDATE_CONTRACTS=1`.
#[test]
fn the_v1_fixture_loads() {
    if std::env::var_os("UPDATE_CONTRACTS").is_some() && !std::path::Path::new(FIXTURE).exists() {
        let mut p = profile();
        history::install_active(&mut p, record(35.0));
        std::fs::create_dir_all(std::path::Path::new(FIXTURE).parent().unwrap()).unwrap();
        std::fs::write(FIXTURE, serde_json::to_string_pretty(&p).unwrap() + "\n").unwrap();
    }
    let p = lynx_sight_profile::store::parse(&std::fs::read_to_string(FIXTURE).unwrap()).unwrap();
    assert!(p.active.is_some());
}
