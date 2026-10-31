//! The desktop app's state and commands, free of any window toolkit.
//!
//! The Tauri shell (`app/src-tauri`) is a thin wrapper that forwards each command here, so the
//! whole command surface is testable headless against the real engine. Command names and
//! argument names are the UI's (`app/src/lib/backend.ts`).

use std::path::PathBuf;

use lynx_sight_contracts::app::{
    AppStatus, Compatibility, CompatibilityStatus, DisplaySetup, EngineState, ProfileSummary,
    SessionView, SourceChoice, UiPresentation,
};
use lynx_sight_contracts::calibration::{CollectionSummary, TargetPlan, TimeSpan};
use lynx_sight_contracts::display::{Display, DisplayCalibration, DisplayLayout};
use lynx_sight_contracts::engine::{SourceSpec, SyntheticScenario};
use lynx_sight_contracts::metric::Provenance;
use lynx_sight_contracts::profile::{Profile, RigConfig, Workflow};
use lynx_sight_contracts::tracking::{BaselineStage, BaselineStageResult, TrackingStatus};
use lynx_sight_geometry::discovery::{DisplayDiscovery, PlatformMonitor};
use lynx_sight_profile::ProfileStore;

use crate::clock::{map_presentation, monotonic_ns, UiClock};
use crate::compatibility::{assess, Conditions};
use crate::engine::{Engine, EngineCommand};
use crate::workflow::{new_profile, CalibrationSession};

/// Command errors reach the UI as text.
pub type CommandResult<T> = std::result::Result<T, String>;

fn text<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

const CLOCK_SAMPLES: usize = 20;

pub struct AppCore {
    pub store: ProfileStore,
    pub command: EngineCommand,
    discovery: Box<dyn DisplayDiscovery + Send>,
    platform: Vec<PlatformMonitor>,
    layout: DisplayLayout,
    engine: Option<EngineState>,
    session: Option<CalibrationSession>,
    clock_samples: Vec<(f64, i64)>,
    background_brightness: Option<f64>,
}

impl AppCore {
    pub fn new(
        store: ProfileStore,
        command: EngineCommand,
        discovery: Box<dyn DisplayDiscovery + Send>,
        platform: Vec<PlatformMonitor>,
    ) -> Self {
        let layout = discovery.discover(&platform);
        AppCore {
            store,
            command,
            discovery,
            platform,
            layout,
            engine: None,
            session: None,
            clock_samples: Vec::new(),
            background_brightness: None,
        }
    }

    /// Starts the engine once to learn whether it runs at all; the answer is kept.
    fn engine_state(&mut self) -> EngineState {
        self.engine
            .get_or_insert_with(|| match Engine::start(&self.command) {
                Ok(e) => EngineState::Running {
                    engine_version: e.engine_version.clone(),
                    landmarks: e.capabilities.landmarks,
                },
                Err(e) => EngineState::Unavailable {
                    reason: e.to_string(),
                },
            })
            .clone()
    }

    pub fn status(&mut self) -> AppStatus {
        AppStatus {
            app_version: crate::APP_VERSION.into(),
            engine: self.engine_state(),
            displays: self.layout.clone(),
            profile_dir: self.store.dir().display().to_string(),
        }
    }

    /// Discovers the displays again, with the window system's current monitors.
    pub fn rediscover_displays(&mut self, platform: Option<Vec<PlatformMonitor>>) -> AppStatus {
        if let Some(p) = platform {
            self.platform = p;
        }
        self.layout = self.discovery.discover(&self.platform);
        self.status()
    }

    pub fn list_profiles(&self) -> CommandResult<Vec<ProfileSummary>> {
        let entries = self.store.list().map_err(text)?;
        Ok(entries
            .into_iter()
            .map(|e| match (&e.problem, self.store.load(&e.profile_id)) {
                (None, Ok(p)) => summary(&p),
                (problem, loaded) => ProfileSummary {
                    profile_id: e.profile_id,
                    name: e.name,
                    updated_at: e.updated_at,
                    display_name: None,
                    has_model: false,
                    active_validation: None,
                    problem: problem.clone().or(loaded.err().map(text)),
                },
            })
            .collect())
    }

    pub fn create_profile(
        &mut self,
        name: &str,
        setup: &DisplaySetup,
    ) -> CommandResult<ProfileSummary> {
        let display = self
            .layout
            .displays
            .get(setup.display_index as usize)
            .cloned()
            .ok_or_else(|| format!("no display {}", setup.display_index))?;
        let calibration = display_calibration(display, setup);
        let engine_version = match self.engine_state() {
            EngineState::Running { engine_version, .. } => Some(engine_version),
            EngineState::Unavailable { .. } => None,
        };
        // The source is recorded when the profile is first calibrated.
        let rig = RigConfig {
            source: "unset".into(),
            baseline_mm: None,
            cameras: vec![],
        };
        let profile = new_profile(name, calibration, rig, engine_version);
        self.store.save(&profile).map_err(text)?;
        Ok(summary(&profile))
    }

    pub fn delete_profile(&mut self, profile_id: &str) -> CommandResult<()> {
        if self
            .session
            .as_ref()
            .is_some_and(|s| s.profile.profile_id == profile_id)
        {
            return Err("the profile is in use by the running session".into());
        }
        self.store.delete(profile_id).map_err(text)
    }

    /// The display a profile was calibrated on, as it is connected now.
    fn current_display(&self, profile: &Profile) -> Option<&Display> {
        let then = &profile.display.display.id;
        self.layout
            .displays
            .iter()
            .find(|d| match (&then.stable, &d.id.stable) {
                (Some(a), Some(b)) => a == b,
                _ => then.connector.is_some() && then.connector == d.id.connector,
            })
    }

    pub fn compatibility(
        &self,
        profile_id: &str,
        source: &SourceChoice,
    ) -> CommandResult<Compatibility> {
        let profile = self.store.load(profile_id).map_err(text)?;
        if profile.active.is_none() {
            return Ok(Compatibility {
                status: CompatibilityStatus::Unknown,
                reasons: vec!["not calibrated yet".into()],
            });
        }
        let Some(display) = self.current_display(&profile) else {
            return Ok(Compatibility {
                status: CompatibilityStatus::Incompatible,
                reasons: vec![format!("{} is not connected", profile.display.display.name)],
            });
        };
        // The engine reports its feature set when a source opens; until then the profile's
        // own is assumed, and starting a session checks it.
        let feature_set = profile
            .active
            .as_ref()
            .map(|a| a.model.feature_set.clone())
            .unwrap_or_default();
        Ok(assess(
            &profile,
            &Conditions {
                display,
                source: source_name(source),
                feature_set: &feature_set,
                tracking: None,
            },
        ))
    }

    pub fn start_session(
        &mut self,
        profile_id: &str,
        workflow: Workflow,
        source: &SourceChoice,
    ) -> CommandResult<SessionView> {
        self.session = None; // ends the previous engine process
        let mut profile = self.store.load(profile_id).map_err(text)?;
        if profile.active.is_none() {
            profile.rig.source = source_name(source).into();
        }
        let engine = Engine::start(&self.command).map_err(text)?;
        let spec = source_spec(source);
        let session = CalibrationSession::start(engine, spec, profile, workflow).map_err(text)?;
        self.clock_samples.clear();
        self.background_brightness = None;
        let view = session.view();
        self.session = Some(session);
        Ok(view)
    }

    pub fn end_session(&mut self) {
        self.session = None;
    }

    fn running(&mut self) -> CommandResult<&mut CalibrationSession> {
        self.session
            .as_mut()
            .ok_or_else(|| "no calibration session is running".to_string())
    }

    /// The running session's engine time origin (for headless drivers and tests).
    pub fn session_clock_origin(&self) -> Option<i64> {
        self.session.as_ref().map(|s| s.clock_origin_ns)
    }

    pub fn session(&self) -> Option<SessionView> {
        self.session.as_ref().map(CalibrationSession::view)
    }

    pub fn tracking(&mut self) -> CommandResult<TrackingStatus> {
        self.running()?.tracking_status().map_err(text)
    }

    /// One clock sync sample: the UI's `performance.now()` at sending, this core's
    /// monotonic time at receipt.
    pub fn sync_clock(&mut self, ui_now_ms: f64) {
        self.sync_clock_at(ui_now_ms, monotonic_ns());
    }

    pub fn sync_clock_at(&mut self, ui_now_ms: f64, mono_ns: i64) {
        if self.clock_samples.len() == CLOCK_SAMPLES {
            self.clock_samples.remove(0);
        }
        self.clock_samples.push((ui_now_ms, mono_ns));
    }

    fn clock(&self) -> CommandResult<UiClock> {
        UiClock::from_samples(&self.clock_samples)
            .ok_or_else(|| "the UI clock is not synchronised yet".to_string())
    }

    pub fn capture_baseline(
        &mut self,
        stage: BaselineStage,
        start_ms: f64,
        end_ms: f64,
    ) -> CommandResult<BaselineStageResult> {
        let clock = self.clock()?;
        let session = self.running()?;
        match session.current_step() {
            Some(lynx_sight_contracts::app::Step::Baseline { stage: s }) if *s == stage => {}
            _ => {
                return Err(format!(
                    "the current step is not the {stage:?} baseline stage"
                ))
            }
        }
        let span = TimeSpan {
            start_ns: clock.to_monotonic(start_ms),
            end_ns: clock.to_monotonic(end_ms),
        };
        session.capture_baseline(span).map_err(text)
    }

    pub fn plan(&mut self) -> CommandResult<TargetPlan> {
        self.running()?.plan().map_err(text)
    }

    pub fn submit(&mut self, presentation: &UiPresentation) -> CommandResult<CollectionSummary> {
        let clock = self.clock()?;
        self.background_brightness = Some(presentation.background_brightness);
        self.running()?
            .submit(map_presentation(presentation, &clock))
            .map_err(text)
    }

    pub fn restart_step(&mut self) -> CommandResult<SessionView> {
        let s = self.running()?;
        s.restart_step();
        Ok(s.view())
    }

    pub fn skip_step(&mut self) -> CommandResult<SessionView> {
        let s = self.running()?;
        s.skip_step().map_err(text)?;
        Ok(s.view())
    }

    pub fn redo(&mut self, index: usize) -> CommandResult<SessionView> {
        let s = self.running()?;
        s.redo(index).map_err(text)?;
        Ok(s.view())
    }

    pub fn run_model_step(&mut self) -> CommandResult<SessionView> {
        let s = self.running()?;
        s.run_model_step().map_err(text)?;
        Ok(s.view())
    }

    pub fn accept(&mut self, confirmed: bool) -> CommandResult<SessionView> {
        let brightness = self.background_brightness;
        let session = self
            .session
            .as_mut()
            .ok_or("no calibration session is running")?;
        if let Some(b) = brightness {
            session.set_background_brightness(b);
        }
        session.accept(&self.store, confirmed).map_err(text)?;
        Ok(session.view())
    }

    pub fn decline(&mut self) -> CommandResult<SessionView> {
        let session = self
            .session
            .as_mut()
            .ok_or("no calibration session is running")?;
        session.decline(&self.store).map_err(text)?;
        Ok(session.view())
    }
}

fn summary(p: &Profile) -> ProfileSummary {
    ProfileSummary {
        profile_id: p.profile_id.clone(),
        name: Some(p.name.clone()),
        updated_at: Some(p.updated_at.clone()),
        display_name: Some(p.display.display.name.clone()),
        has_model: p.active.is_some(),
        active_validation: p.active.as_ref().map(|a| a.validation.clone()),
        problem: None,
    }
}

fn source_name(source: &SourceChoice) -> &'static str {
    match source {
        SourceChoice::Synthetic { .. } => "synthetic",
        SourceChoice::Cameras { .. } => "cameras",
    }
}

/// The engine's source. A relative experiment config is taken from the working directory, or
/// else the repository (the default `software/diagnostic/exp.yaml` is repository-relative).
fn source_spec(source: &SourceChoice) -> SourceSpec {
    match source {
        SourceChoice::Synthetic { seed, scenario } => SourceSpec::Synthetic {
            scenario: scenario.clone().unwrap_or_else(SyntheticScenario::default),
            seed: *seed,
        },
        SourceChoice::Cameras { experiment_config } => {
            let path = PathBuf::from(experiment_config);
            let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../..");
            let resolved = if path.is_relative() && !path.exists() && repo.join(&path).exists() {
                repo.join(&path)
            } else {
                path
            };
            SourceSpec::Cameras {
                experiment_config: resolved.display().to_string(),
            }
        }
    }
}

/// A profile's display: the discovered one with the user's measurements, which replace EDID
/// estimates; values the user leaves out stay unknown.
pub fn display_calibration(display: Display, setup: &DisplaySetup) -> DisplayCalibration {
    let display = match (setup.measured_width_mm, setup.measured_height_mm) {
        (Some(w), Some(h)) if w > 0.0 && h > 0.0 => {
            lynx_sight_geometry::discovery::with_measured_size(display, w, h)
        }
        _ => display,
    };
    let screen_pose = match (setup.rig_above_screen_mm, setup.screen_behind_rig_mm) {
        (Some(above), Some(behind)) => {
            lynx_sight_geometry::screen_pose_below_rig(&display, above, behind).map(|mut p| {
                p.provenance = Provenance::UserMeasured;
                p
            })
        }
        _ => None,
    };
    DisplayCalibration {
        display,
        screen_pose,
        viewing_distance_mm: setup.viewing_distance_mm,
        viewing_distance_provenance: setup.viewing_distance_mm.map(|_| Provenance::UserMeasured),
    }
}
