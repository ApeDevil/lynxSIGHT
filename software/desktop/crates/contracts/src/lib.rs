//! The data contracts LYNX SIGHT stores and exchanges, owned here and nowhere else.
//!
//! * [`engine`]: the line-delimited JSON protocol between the desktop core (Rust) and the vision
//!   engine (Python, `sight-engine`), versioned by [`ENGINE_PROTOCOL_VERSION`].
//! * [`display`]: displays, their layout and their physical geometry.
//! * [`calibration`]: target plans, presentations, gaze models, validation reports and the face
//!   baseline, which the engine produces and the core stores.
//! * [`profile`]: the persisted calibration profile, versioned by [`PROFILE_SCHEMA_VERSION`].
//! * [`pointer`]: pointer intent, for the dry-run pointer backend.
//! * [`app`]: what the desktop core shows the UI.
//!
//! JSON Schemas (for the Python engine's tests) and TypeScript types (for the UI) are generated
//! from these types; see [`schema`] and `contracts/README.md`. Units and coordinate systems are
//! defined in `docs/architecture/coordinate-systems.md`.

pub mod app;
pub mod calibration;
pub mod display;
pub mod engine;
pub mod metric;
pub mod pointer;
pub mod profile;
pub mod schema;
pub mod tracking;

/// Version of the engine protocol. A peer speaking another version is refused at `hello`.
pub const ENGINE_PROTOCOL_VERSION: u32 = 1;
/// Version of the stored profile schema. Older versions are migrated on load
/// (`lynx-sight-profile`); newer ones are refused.
pub const PROFILE_SCHEMA_VERSION: u32 = 1;
/// The `schema` tag every stored profile carries.
pub const PROFILE_SCHEMA_ID: &str = "lynx-sight/profile";
