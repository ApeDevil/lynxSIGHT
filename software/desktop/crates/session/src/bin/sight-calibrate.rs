//! Headless calibration runs on the simulated user, for demonstration and CI:
//!
//! ```text
//! sight-calibrate demo [--profile-dir DIR] [--seed N] [--drift DU,DV]
//! ```
//!
//! Runs a full calibration, then a quick recalibration after introducing feature drift, then
//! one more without further drift, saving the profile after each. Results are synthetic.

use std::path::PathBuf;
use std::process::ExitCode;

use lynx_sight_profile::ProfileStore;
use lynx_sight_session::demo;
use lynx_sight_session::engine::EngineCommand;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) != Some("demo") {
        eprintln!("usage: sight-calibrate demo [--profile-dir DIR] [--seed N] [--drift DU,DV]");
        return ExitCode::from(2);
    }
    let mut dir = std::env::temp_dir().join("lynx-sight-demo-profiles");
    let mut seed = 1u64;
    let mut drift = [0.02, -0.015];
    let mut it = args[1..].iter();
    while let Some(a) = it.next() {
        let value = it.next();
        match (a.as_str(), value) {
            ("--profile-dir", Some(v)) => dir = PathBuf::from(v),
            ("--seed", Some(v)) => seed = v.parse().unwrap_or(seed),
            ("--drift", Some(v)) => {
                let parts: Vec<f64> = v.split(',').filter_map(|p| p.parse().ok()).collect();
                if parts.len() == 2 {
                    drift = [parts[0], parts[1]];
                }
            }
            _ => {
                eprintln!("unknown or incomplete argument {a}");
                return ExitCode::from(2);
            }
        }
    }
    let store = ProfileStore::new(&dir);
    println!("synthetic demonstration (simulated user and display; not a hardware result)");
    match demo::full_then_quick(&EngineCommand::from_env(), &store, seed, drift) {
        Ok((profile, outcomes)) => {
            for o in &outcomes {
                println!("  {}", demo::describe(o));
            }
            println!(
                "profile {} saved in {} ({} history records)",
                profile.profile_id,
                dir.display(),
                profile.history.len()
            );
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
