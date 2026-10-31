//! Calibration sessions, from the desktop core's side.
//!
//! * [`app`]: the desktop app's commands, wrapped by the Tauri shell.
//! * [`engine`]: starting `sight-engine` and talking the protocol to it.
//! * [`clock`]: CLOCK_MONOTONIC, and mapping UI timestamps onto it.
//! * [`workflow`]: the steps of full calibration and quick recalibration, and the session that
//!   walks through them.
//! * [`acceptance`]: when a candidate model may replace the active one.
//! * [`compatibility`]: whether a profile still fits the current conditions.
//! * [`presenter`]: a simulated presenter for headless runs and tests.
//! * [`pointer`]: pointer intent and the dry-run backend (no input is injected).

pub mod acceptance;
pub mod app;
pub mod clock;
pub mod compatibility;
pub mod demo;
pub mod engine;
pub mod pointer;
pub mod presenter;
pub mod workflow;

pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
