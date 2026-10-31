# LYNX SIGHT

Experimental optical input device of the LYNXware ecosystem: cameras that track the eyes, head
and, later, gestures, for computer input. This repository holds the v0.1 prototype.

| Path | Contents |
|---|---|
| `software/diagnostic/` | Linux dual-camera diagnostic tool and the `sight-engine` vision engine ([README](software/diagnostic/README.md)) |
| `software/desktop/` | calibration app: Rust core, Svelte UI, Tauri shell ([README](software/desktop/README.md)) |
| `contracts/` | versioned schemas shared by the engine, the core and the UI ([README](contracts/README.md)) |
| `hardware/` | 3D-printable camera mount |
| `docs/architecture/` | shared interfaces ([cameras, rig frame, experiment config](docs/architecture/shared-interface.md)), [desktop calibration](docs/architecture/desktop-calibration.md), [coordinate systems](docs/architecture/coordinate-systems.md), [pointer integration](docs/architecture/pointer-integration.md) |
| `docs/testing/` | test plans and results ([camera hardware tests](docs/testing/hardware-test-plan.md), [calibration validation](docs/testing/calibration-validation-guide.md)) |
| `docs/hardware/` | camera and mount hardware documentation |
