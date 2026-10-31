//! Installing calibration records. The previous active record is never lost: it moves to the
//! history as superseded, and rejected candidates are kept there too, for comparison.
//! Whether a candidate may become active is the session's policy; this module only keeps the
//! books.

use lynx_sight_contracts::profile::{CalibrationRecord, Profile, RecordStatus};

use crate::validate::MAX_HISTORY;

/// Makes `record` the active one; the old active record becomes superseded history.
pub fn install_active(profile: &mut Profile, mut record: CalibrationRecord) {
    record.status = RecordStatus::Active;
    if let Some(mut old) = profile.active.take() {
        old.status = RecordStatus::Superseded;
        push_history(profile, old);
    }
    profile.active = Some(record);
    profile.updated_at = crate::now_rfc3339();
}

/// Keeps a declined candidate for later comparison; the active record is unchanged.
pub fn add_rejected(profile: &mut Profile, mut record: CalibrationRecord) {
    record.status = RecordStatus::Rejected;
    push_history(profile, record);
    profile.updated_at = crate::now_rfc3339();
}

/// Brings back a history record as active (an explicit user action, e.g. "undo").
pub fn restore(profile: &mut Profile, record_id: &str) -> bool {
    let Some(i) = profile
        .history
        .iter()
        .position(|r| r.record_id == record_id)
    else {
        return false;
    };
    let record = profile.history.remove(i);
    install_active(profile, record);
    true
}

fn push_history(profile: &mut Profile, record: CalibrationRecord) {
    profile.history.insert(0, record);
    profile.history.truncate(MAX_HISTORY);
}
