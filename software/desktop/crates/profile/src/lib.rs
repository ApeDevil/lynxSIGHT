//! Calibration profiles on local disk.
//!
//! * [`store`]: one JSON file per profile, written atomically, listed and loaded safely.
//! * [`validate`]: what a loadable profile must satisfy beyond its schema.
//! * [`migrate`]: the upgrade path from older schema versions.
//! * [`history`]: installing a new calibration record without losing the previous one.

pub mod history;
pub mod migrate;
pub mod store;
pub mod validate;

pub use store::{ProfileEntry, ProfileError, ProfileStore};

/// The current time as RFC 3339 UTC, the timestamp format of every profile field.
pub fn now_rfc3339() -> String {
    time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .expect("UTC times format")
}

/// A new random identifier (profiles and records). Random, so it carries nothing about the
/// person.
pub fn new_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}
