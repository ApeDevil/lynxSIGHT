//! Semantic checks a profile must pass to be used, beyond deserializing.

use lynx_sight_contracts::profile::{Profile, RecordStatus};
use lynx_sight_contracts::{PROFILE_SCHEMA_ID, PROFILE_SCHEMA_VERSION};

pub const MAX_NAME_LEN: usize = 64;
pub const MAX_HISTORY: usize = 20;

/// Every problem found; empty means valid.
pub fn problems(p: &Profile) -> Vec<String> {
    let mut out = Vec::new();
    if p.schema != PROFILE_SCHEMA_ID || p.schema_version != PROFILE_SCHEMA_VERSION {
        out.push(format!(
            "schema {} v{} is not current",
            p.schema, p.schema_version
        ));
    }
    if !is_id(&p.profile_id) {
        out.push("profile_id must be 32 lowercase hex digits".into());
    }
    let name = p.name.trim();
    if name.is_empty() || name.chars().count() > MAX_NAME_LEN || name.chars().any(char::is_control)
    {
        out.push(format!(
            "name must be 1-{MAX_NAME_LEN} printable characters"
        ));
    }
    for (label, t) in [("created_at", &p.created_at), ("updated_at", &p.updated_at)] {
        if time::OffsetDateTime::parse(t, &time::format_description::well_known::Rfc3339).is_err() {
            out.push(format!("{label} is not RFC 3339"));
        }
    }
    let d = &p.display.display;
    if d.mode.width == 0 || d.mode.height == 0 || d.desktop.width == 0 || d.desktop.height == 0 {
        out.push("display has a zero size".into());
    }
    if !(d.scale_factor.is_finite() && d.scale_factor > 0.0) {
        out.push("display scale factor must be positive".into());
    }
    if let Some(phys) = d.physical {
        if !(phys.width_mm > 0.0 && phys.height_mm > 0.0) {
            out.push("physical display size must be positive".into());
        }
    }
    if let Some(active) = &p.active {
        if active.status != RecordStatus::Active {
            out.push("the active record is not marked active".into());
        }
    }
    if p.history.iter().any(|r| r.status == RecordStatus::Active) {
        out.push("a history record is marked active".into());
    }
    if p.history.len() > MAX_HISTORY {
        out.push(format!("history longer than {MAX_HISTORY}"));
    }
    out
}

pub fn is_id(s: &str) -> bool {
    s.len() == 32
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
