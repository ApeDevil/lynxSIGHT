use std::path::PathBuf;

use lynx_sight_contracts::calibration::*;
use lynx_sight_contracts::engine::*;
use lynx_sight_contracts::metric::*;
use lynx_sight_contracts::schema::{render, root_schemas};

fn schema_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../../contracts/schemas")
}

/// The committed schemas must match the Rust types. Regenerate with
/// `UPDATE_CONTRACTS=1 cargo test -p lynx-sight-contracts`.
#[test]
fn schemas_are_up_to_date() {
    let update = std::env::var_os("UPDATE_CONTRACTS").is_some();
    let mut stale = Vec::new();
    for (name, schema) in root_schemas() {
        let path = schema_dir().join(name);
        let text = render(&schema);
        if update {
            std::fs::write(&path, &text).unwrap();
        } else if std::fs::read_to_string(&path).ok().as_deref() != Some(text.as_str()) {
            stale.push(name);
        }
    }
    assert!(
        stale.is_empty(),
        "stale schemas {stale:?}: run UPDATE_CONTRACTS=1 cargo test"
    );
}

#[test]
fn envelope_flattens_the_tagged_body() {
    let request = Envelope {
        protocol: 1,
        id: 7,
        body: Request::Plan {
            request: PlanRequest::Stationary {
                purpose: Purpose::Fit,
                layout: StationaryLayout::CentreEdgesCorners { margin: 0.08 },
                settle_ms: 700,
                dwell_ms: 1200,
                aspect: 16.0 / 9.0,
            },
        },
    };
    let json = serde_json::to_value(&request).unwrap();
    assert_eq!(json["type"], "plan");
    assert_eq!(json["protocol"], 1);
    assert_eq!(json["request"]["method"], "stationary");
    assert_eq!(json["request"]["layout"]["layout"], "centre_edges_corners");
    let back: Envelope<Request> = serde_json::from_value(json).unwrap();
    assert_eq!(back, request);
}

#[test]
fn unavailable_metrics_carry_a_reason() {
    let m: Metric = serde_json::from_str(r#"{"status":"unavailable","reason":"no size"}"#).unwrap();
    assert_eq!(m.value(), None);
    let json = serde_json::to_string(&Metric::available(1.5)).unwrap();
    assert_eq!(json, r#"{"status":"available","value":1.5}"#);
}

#[test]
fn unit_variants_serialize_as_bare_tags() {
    let json = serde_json::to_string(&Envelope {
        protocol: 1,
        id: 1,
        body: Request::Shutdown,
    })
    .unwrap();
    assert_eq!(json, r#"{"protocol":1,"id":1,"type":"shutdown"}"#);
    let ok: Envelope<Response> =
        serde_json::from_str(r#"{"protocol":1,"id":1,"type":"ok"}"#).unwrap();
    assert_eq!(ok.body, Response::Ok);
}

/// The Python engine's `simulation.default_scenario()` is checked against this fixture.
#[test]
fn default_synthetic_scenario_fixture_is_up_to_date() {
    let path = schema_dir().join("../fixtures/synthetic-scenario.default.json");
    let text = serde_json::to_string_pretty(&SyntheticScenario::default()).unwrap() + "\n";
    if std::env::var_os("UPDATE_CONTRACTS").is_some() {
        std::fs::write(&path, &text).unwrap();
    }
    assert_eq!(
        std::fs::read_to_string(&path).unwrap(),
        text,
        "run UPDATE_CONTRACTS=1 cargo test"
    );
}
