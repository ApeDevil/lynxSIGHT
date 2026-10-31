# Calibration: hardware validation guide

Everything the calibration foundation does has so far run **only on the synthetic user**
(`simulation.py`) and, for the app window, under a virtual X server. None of it has seen the
OV9281 cameras. This guide is the first camera session, in priority order: stop at the first
failure and record it. Results go in the table at the end, marked hardware-verified.

Prerequisites: hardware tests H1, H2, H7, H11 and H12 of the
[camera test plan](hardware-test-plan.md) pass, the fixed rig (baseline about 257 mm) sits on the
monitor, and the two cameras are on separate USB controllers (the shared Genesys hub dropped
frames). Both cameras report serial UC762, so `exp.yaml` must bind them by USB port path.

## Setup

```sh
# once: system libraries for the Tauri window (Ubuntu)
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev build-essential
cd software/diagnostic && uv sync --extra landmarks && uv run sight-diag models fetch face_landmarker
cd ../desktop/app && npm ci
# the engine with MediaPipe landmarks (iris-in-eye features); without them it falls back to
# pupil-offset features
export LYNX_SIGHT_ENGINE="uv run --quiet --project $PWD/../../diagnostic --extra landmarks sight-engine"
npm run tauri dev
```

Software-only sanity check first (no cameras, about a minute):
`cd software/desktop && cargo run -p lynx-sight-session --bin sight-calibrate -- demo`.

## First camera session (priority order)

| # | Check | How | Pass when | Record |
|---|---|---|---|---|
| C1 | Engine and landmarks | start the app | no "vision engine unavailable"; source "Cameras" with your `exp.yaml` path | engine message |
| C2 | Displays | Displays panel | every monitor listed with the right desktop position (negative offsets included), mode, scale; physical size marked `edid` | the table; wrong values |
| C3 | Profile with measurements | measure the visible area with a ruler, the rig height above the screen's top edge and the screen's depth behind the rig origin; create a profile | profile saved; size shows `user_measured` | the measured values |
| C4 | Tracking status | start a full calibration with Cameras | both cameras `streaming`, fps near the configured mode, both eyes `tracked`, guidance sensible when you move left/right/closer | fps, latency, guidance shown |
| C5 | Feature set | session header | `iris-in-eye/v1` (landmarks) — `pupil-offset/v1` means MediaPipe is not in use | which |
| C6 | Baseline | the three stages | all three pass; if "detect stable" fails, note the message | messages, sample counts |
| C7 | Stationary targets | step 4 | 9/9 targets usable; accepted share above 50 % | counts, rejection reasons |
| C8 | Pursuit | spiral and edges | lag estimate 50–200 ms and similar for both; "followed" above 0.7 | both lags, followed |
| C9 | Validation and fit | steps 7–8, review | the review shows a median error; mm and ° appear (geometry measured) | median/RMS/p90 in px, mm, °; heatmap screenshot |
| C10 | Sanity of the number | look at a validation-like point and compare to the heatmap | errors match where you saw the target drift | notes |
| C11 | Profile persistence | restart the app | profile listed as calibrated with the same median | — |
| C12 | Quick recalibration | move the chair 10 cm back, run Quick | the comparison verdict is shown; a better candidate installs, an equivalent one is declined | verdict, both medians |
| C13 | Lighting | repeat C4 with the desk lamp off/on | where tracking guidance changes | notes |
| C14 | Throughput | while calibrating, watch fps | fps holds (sight-diag reached ~68 fps on MJPEG decode; the engine runs landmarks at 60 Hz) | fps under load |

Personal data: the app saves no images. Screenshots of the review are fine; keep camera
snapshots local.

## Known open points to watch

* The edges pursuit gave a 150 ms lag estimate in the virtual-display GUI run (spiral 90 ms,
  simulated truth 80 ms); headless runs give 70–100 ms for both. Probably irregular frame timing
  under software rendering, not yet confirmed. Compare C8's two lags.
* The real-camera feature source (`CameraFeatures`) has never run on hardware.
* Head pose from landmarks is uncalibrated; the model uses only head position terms.

## Results

| Date | Check | Result | Notes |
|---|---|---|---|
| | | | |
