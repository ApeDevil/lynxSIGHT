# LYNX SIGHT desktop

The calibration app: a Rust core with a Svelte UI in a Tauri 2 window. Vision (capture,
features, gaze fitting, evaluation) runs in the Python engine `sight-engine`
([software/diagnostic](../diagnostic/README.md)), which the core starts as a child process and
talks to over JSON lines. Why it is split this way:
[desktop calibration architecture](../../docs/architecture/desktop-calibration.md).

| Path | Owns |
|---|---|
| `crates/contracts` | every versioned contract; generates `contracts/schemas` and `app/src/lib/contracts` |
| `crates/geometry` | display discovery (window system, sysfs EDID, xrandr), coordinate transforms |
| `crates/profile` | profile files: atomic writes, validation, migration, history |
| `crates/session` | engine client, UI clock, workflows, acceptance policy, compatibility, pointer intent (dry run), the app commands (`app.rs`), the `sight-calibrate` CLI |
| `app/` | Svelte UI; `app/src-tauri` is the thin Tauri shell |

## Run

```sh
cargo test                                   # core crates; integration tests start sight-engine via uv
cargo run -p lynx-sight-session --bin sight-calibrate -- demo   # synthetic, headless
cd app && npm ci && npm run tauri dev        # the app (needs WebKitGTK 4.1, see below)
```

Checks: `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
`cd app && npm run check && npm test`. After changing a contract:
`UPDATE_CONTRACTS=1 cargo test -p lynx-sight-contracts`.

The engine command defaults to `uv run --project software/diagnostic sight-engine`;
`LYNX_SIGHT_ENGINE` overrides it (for example to add `--extra landmarks`). Profiles live in
`$XDG_DATA_HOME/lynx-sight/profiles` (default `~/.local/share/lynx-sight/profiles`). They hold
models and metrics, never images.

The Tauri shell is a workspace member but not a default member: building it needs
`libwebkit2gtk-4.1-dev`, `libgtk-3-dev` and `librsvg2-dev` (Ubuntu). Use
`cargo build -p lynx-sight-app` or `npm run tauri dev`.

## Dependencies and licences

All direct dependencies are permissively licensed (MIT and/or Apache-2.0): serde, serde_json,
schemars, ts-rs, thiserror, time, rustix, uuid, tempfile (tests), tauri and tauri-build; Svelte,
Vite, TypeScript, svelte-check, Vitest, jsdom and Testing Library (MIT), @tauri-apps/api and
@tauri-apps/cli (MIT/Apache-2.0). The app icon is generated in the repository. `npm install`
reports two low-severity advisories in `deepmerge` via the Svelte Vite plugin (build-time only).
