//! The Tauri shell: one window, and each UI command forwarded to the toolkit-free
//! [`AppCore`]. Nothing is decided here; the window system only contributes its monitor list
//! to display discovery.

use std::sync::Mutex;

use lynx_sight_contracts::app::{
    AppStatus, Compatibility, DisplaySetup, ProfileSummary, SessionView, SourceChoice,
    UiPresentation,
};
use lynx_sight_contracts::calibration::{CollectionSummary, TargetPlan};
use lynx_sight_contracts::profile::Workflow;
use lynx_sight_contracts::tracking::{BaselineStage, BaselineStageResult, TrackingStatus};
use lynx_sight_geometry::discovery::{LinuxDiscovery, PlatformMonitor};
use lynx_sight_profile::ProfileStore;
use lynx_sight_session::app::{AppCore, CommandResult};
use lynx_sight_session::engine::EngineCommand;
use tauri::{AppHandle, Manager, State};

type Core<'a> = State<'a, Mutex<AppCore>>;

fn lock<'a>(core: &'a Core) -> std::sync::MutexGuard<'a, AppCore> {
    // A panicked command must not lock the app for good.
    core.lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

/// The window system's monitors, in desktop coordinates.
fn platform_monitors(app: &AppHandle) -> Vec<PlatformMonitor> {
    let primary = app.primary_monitor().ok().flatten().map(|m| *m.position());
    app.available_monitors()
        .unwrap_or_default()
        .iter()
        .map(|m| {
            let scale = m.scale_factor();
            let size = m.size().to_logical::<f64>(scale);
            let pos = m.position();
            PlatformMonitor {
                name: m.name().cloned(),
                x: pos.x,
                y: pos.y,
                width: size.width.round() as u32,
                height: size.height.round() as u32,
                scale_factor: scale,
                primary: primary == Some(*pos),
            }
        })
        .collect()
}

// Every command is `async` so Tauri runs it off the main thread: engine requests block.

#[tauri::command(async)]
fn status(core: Core) -> AppStatus {
    lock(&core).status()
}

#[tauri::command(async)]
fn rediscover_displays(app: AppHandle, core: Core) -> AppStatus {
    lock(&core).rediscover_displays(Some(platform_monitors(&app)))
}

#[tauri::command(async)]
fn list_profiles(core: Core) -> CommandResult<Vec<ProfileSummary>> {
    lock(&core).list_profiles()
}

#[tauri::command(async)]
fn create_profile(core: Core, name: String, setup: DisplaySetup) -> CommandResult<ProfileSummary> {
    lock(&core).create_profile(&name, &setup)
}

#[tauri::command(async, rename_all = "camelCase")]
fn delete_profile(core: Core, profile_id: String) -> CommandResult<()> {
    lock(&core).delete_profile(&profile_id)
}

#[tauri::command(async, rename_all = "camelCase")]
fn compatibility(
    core: Core,
    profile_id: String,
    source: SourceChoice,
) -> CommandResult<Compatibility> {
    lock(&core).compatibility(&profile_id, &source)
}

#[tauri::command(async, rename_all = "camelCase")]
fn start_session(
    core: Core,
    profile_id: String,
    workflow: Workflow,
    source: SourceChoice,
) -> CommandResult<SessionView> {
    lock(&core).start_session(&profile_id, workflow, &source)
}

#[tauri::command(async)]
fn end_session(core: Core) {
    lock(&core).end_session()
}

#[tauri::command(async)]
fn session(core: Core) -> Option<SessionView> {
    lock(&core).session()
}

#[tauri::command(async)]
fn tracking(core: Core) -> CommandResult<TrackingStatus> {
    lock(&core).tracking()
}

#[tauri::command(async, rename_all = "camelCase")]
fn sync_clock(core: Core, ui_now_ms: f64) {
    lock(&core).sync_clock(ui_now_ms)
}

#[tauri::command(async, rename_all = "camelCase")]
fn capture_baseline(
    core: Core,
    stage: BaselineStage,
    start_ms: f64,
    end_ms: f64,
) -> CommandResult<BaselineStageResult> {
    lock(&core).capture_baseline(stage, start_ms, end_ms)
}

#[tauri::command(async)]
fn plan(core: Core) -> CommandResult<TargetPlan> {
    lock(&core).plan()
}

#[tauri::command(async)]
fn submit(core: Core, presentation: UiPresentation) -> CommandResult<CollectionSummary> {
    lock(&core).submit(&presentation)
}

#[tauri::command(async)]
fn restart_step(core: Core) -> CommandResult<SessionView> {
    lock(&core).restart_step()
}

#[tauri::command(async)]
fn skip_step(core: Core) -> CommandResult<SessionView> {
    lock(&core).skip_step()
}

#[tauri::command(async)]
fn redo(core: Core, index: usize) -> CommandResult<SessionView> {
    lock(&core).redo(index)
}

#[tauri::command(async)]
fn run_model_step(core: Core) -> CommandResult<SessionView> {
    lock(&core).run_model_step()
}

#[tauri::command(async)]
fn accept(core: Core, confirmed: bool) -> CommandResult<SessionView> {
    lock(&core).accept(confirmed)
}

#[tauri::command(async)]
fn decline(core: Core) -> CommandResult<SessionView> {
    lock(&core).decline()
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let dir = ProfileStore::default_dir()
                .or_else(|| app.path().app_data_dir().ok().map(|d| d.join("profiles")))
                .ok_or("no directory for profiles")?;
            let core = AppCore::new(
                ProfileStore::new(dir),
                EngineCommand::from_env(),
                Box::new(LinuxDiscovery::default()),
                platform_monitors(app.handle()),
            );
            app.manage(Mutex::new(core));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            status,
            rediscover_displays,
            list_profiles,
            create_profile,
            delete_profile,
            compatibility,
            start_session,
            end_session,
            session,
            tracking,
            sync_clock,
            capture_baseline,
            plan,
            submit,
            restart_step,
            skip_step,
            redo,
            run_model_step,
            accept,
            decline,
        ])
        .run(tauri::generate_context!())
        .expect("the LYNX SIGHT window failed to start");
}
