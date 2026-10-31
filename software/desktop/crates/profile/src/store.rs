//! One JSON file per profile in a directory (default `~/.local/share/lynx-sight/profiles`).
//!
//! Writes are atomic: the new content goes to a temporary file in the same directory, is
//! flushed to disk, and replaces the old file by rename, so a crash leaves either the old or
//! the new profile, never a torn one. The previous file is kept as `<id>.json.bak`.

use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use lynx_sight_contracts::profile::Profile;

use crate::migrate::{self, MigrationError};
use crate::validate::{self, is_id};

#[derive(Debug, thiserror::Error)]
pub enum ProfileError {
    #[error("profile {0} not found")]
    NotFound(String),
    #[error("profile file is not valid JSON: {0}")]
    Json(String),
    #[error(transparent)]
    Migration(#[from] MigrationError),
    #[error("profile does not match the schema: {0}")]
    Schema(String),
    #[error("profile is invalid: {}", .0.join("; "))]
    Invalid(Vec<String>),
    #[error("profile storage: {0}")]
    Io(#[from] std::io::Error),
}

/// A listed profile. Broken or too-new files are listed with their problem, never hidden or
/// overwritten.
#[derive(Debug, Clone, PartialEq)]
pub struct ProfileEntry {
    pub profile_id: String,
    pub name: Option<String>,
    pub updated_at: Option<String>,
    pub problem: Option<String>,
}

pub struct ProfileStore {
    dir: PathBuf,
}

impl ProfileStore {
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        ProfileStore { dir: dir.into() }
    }

    /// `$XDG_DATA_HOME/lynx-sight/profiles`, else `~/.local/share/lynx-sight/profiles`.
    pub fn default_dir() -> Option<PathBuf> {
        let base = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local/share")))?;
        Some(base.join("lynx-sight/profiles"))
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    fn path(&self, id: &str) -> PathBuf {
        self.dir.join(format!("{id}.json"))
    }

    pub fn list(&self) -> Result<Vec<ProfileEntry>, ProfileError> {
        let mut entries = Vec::new();
        let read = match fs::read_dir(&self.dir) {
            Ok(r) => r,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(entries),
            Err(e) => return Err(e.into()),
        };
        for entry in read.flatten() {
            let file = entry.file_name().to_string_lossy().to_string();
            let Some(id) = file.strip_suffix(".json") else {
                continue;
            };
            if !is_id(id) {
                continue;
            }
            entries.push(match self.load(id) {
                Ok(p) => ProfileEntry {
                    profile_id: p.profile_id,
                    name: Some(p.name),
                    updated_at: Some(p.updated_at),
                    problem: None,
                },
                Err(e) => ProfileEntry {
                    profile_id: id.to_string(),
                    name: None,
                    updated_at: None,
                    problem: Some(e.to_string()),
                },
            });
        }
        entries.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
        Ok(entries)
    }

    /// Loads, migrates (in memory only; saving writes the new version) and validates.
    pub fn load(&self, id: &str) -> Result<Profile, ProfileError> {
        if !is_id(id) {
            return Err(ProfileError::NotFound(id.to_string()));
        }
        let text = match fs::read_to_string(self.path(id)) {
            Ok(t) => t,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                return Err(ProfileError::NotFound(id.to_string()))
            }
            Err(e) => return Err(e.into()),
        };
        let profile = parse(&text)?;
        if profile.profile_id != id {
            return Err(ProfileError::Invalid(vec![format!(
                "file {id} holds profile {}",
                profile.profile_id
            )]));
        }
        Ok(profile)
    }

    pub fn save(&self, profile: &Profile) -> Result<(), ProfileError> {
        let problems = validate::problems(profile);
        if !problems.is_empty() {
            return Err(ProfileError::Invalid(problems));
        }
        fs::create_dir_all(&self.dir)?;
        let mut text =
            serde_json::to_string_pretty(profile).map_err(|e| ProfileError::Json(e.to_string()))?;
        text.push('\n');
        let target = self.path(&profile.profile_id);
        let tmp = self.dir.join(format!(
            ".{}.json.{}.tmp",
            profile.profile_id,
            crate::new_id()
        ));
        let result = (|| {
            let mut f = File::create(&tmp)?;
            f.write_all(text.as_bytes())?;
            f.sync_all()?;
            if target.exists() {
                fs::copy(
                    &target,
                    self.dir.join(format!("{}.json.bak", profile.profile_id)),
                )?;
            }
            fs::rename(&tmp, &target)?;
            File::open(&self.dir)?.sync_all()
        })();
        if result.is_err() {
            let _ = fs::remove_file(&tmp);
        }
        Ok(result?)
    }

    pub fn delete(&self, id: &str) -> Result<(), ProfileError> {
        if !is_id(id) {
            return Err(ProfileError::NotFound(id.to_string()));
        }
        fs::remove_file(self.path(id)).map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => ProfileError::NotFound(id.to_string()),
            _ => e.into(),
        })?;
        let _ = fs::remove_file(self.dir.join(format!("{id}.json.bak")));
        Ok(())
    }
}

/// Parses profile JSON of any supported version into a valid current profile.
pub fn parse(text: &str) -> Result<Profile, ProfileError> {
    let value: serde_json::Value =
        serde_json::from_str(text).map_err(|e| ProfileError::Json(e.to_string()))?;
    let (value, _from) = migrate::migrate(value)?;
    let profile: Profile =
        serde_json::from_value(value).map_err(|e| ProfileError::Schema(e.to_string()))?;
    let problems = validate::problems(&profile);
    if problems.is_empty() {
        Ok(profile)
    } else {
        Err(ProfileError::Invalid(problems))
    }
}
