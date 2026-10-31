//! Schema migration. A profile of version N is upgraded by applying the steps N→N+1, … up to
//! [`PROFILE_SCHEMA_VERSION`] on its JSON, before it is deserialized. Each step is a pure
//! function with a fixture of its input version under `tests/fixtures/`. Version 1 is the
//! first, so there are no steps yet.

use lynx_sight_contracts::{PROFILE_SCHEMA_ID, PROFILE_SCHEMA_VERSION};
use serde_json::Value;

/// Upgrades the profile JSON of version `from` to `from + 1`.
pub type Step = fn(Value) -> Result<Value, String>;

/// `STEPS[i]` upgrades version `i + 1` to `i + 2`.
pub const STEPS: &[Step] = &[];

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum MigrationError {
    #[error("not a LYNX SIGHT profile (schema tag {0:?})")]
    NotAProfile(Option<String>),
    #[error(
        "profile schema version {found} is newer than this software ({supported}); not touched"
    )]
    Newer { found: u32, supported: u32 },
    #[error("profile has no valid schema_version")]
    NoVersion,
    #[error("migration from version {from} failed: {reason}")]
    Failed { from: u32, reason: String },
}

/// Returns the profile upgraded to the current version and the version it had.
pub fn migrate(value: Value) -> Result<(Value, u32), MigrationError> {
    migrate_with(value, STEPS, PROFILE_SCHEMA_VERSION)
}

pub fn migrate_with(
    mut value: Value,
    steps: &[Step],
    current: u32,
) -> Result<(Value, u32), MigrationError> {
    let tag = value
        .get("schema")
        .and_then(Value::as_str)
        .map(str::to_string);
    if tag.as_deref() != Some(PROFILE_SCHEMA_ID) {
        return Err(MigrationError::NotAProfile(tag));
    }
    let found = value
        .get("schema_version")
        .and_then(Value::as_u64)
        .and_then(|v| u32::try_from(v).ok())
        .filter(|v| *v >= 1)
        .ok_or(MigrationError::NoVersion)?;
    if found > current {
        return Err(MigrationError::Newer {
            found,
            supported: current,
        });
    }
    for from in found..current {
        let step = steps
            .get((from - 1) as usize)
            .ok_or_else(|| MigrationError::Failed {
                from,
                reason: "no migration step".into(),
            })?;
        value = step(value).map_err(|reason| MigrationError::Failed { from, reason })?;
        value["schema_version"] = Value::from(from + 1);
    }
    Ok((value, found))
}
