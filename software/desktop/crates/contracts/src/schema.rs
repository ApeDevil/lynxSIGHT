//! JSON Schemas of the root contracts, written to `contracts/schemas/` (see the test
//! `schemas_are_up_to_date`). The Python engine validates its messages against them.

use schemars::{schema_for, Schema};

use crate::display::DisplayLayout;
use crate::engine::{Envelope, Request, Response};
use crate::pointer::PointerIntent;
use crate::profile::Profile;

/// File name and schema of every root contract.
pub fn root_schemas() -> Vec<(&'static str, Schema)> {
    vec![
        (
            "engine-request.v1.schema.json",
            schema_for!(Envelope<Request>),
        ),
        (
            "engine-response.v1.schema.json",
            schema_for!(Envelope<Response>),
        ),
        ("profile.v1.schema.json", schema_for!(Profile)),
        ("display-layout.v1.schema.json", schema_for!(DisplayLayout)),
        ("pointer-intent.v1.schema.json", schema_for!(PointerIntent)),
    ]
}

pub fn render(schema: &Schema) -> String {
    let mut text = serde_json::to_string_pretty(schema).expect("schemas serialize");
    text.push('\n');
    text
}
