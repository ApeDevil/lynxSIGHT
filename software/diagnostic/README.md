# LYNX SIGHT vision: diagnostic (`sight-diag`) and calibration engine (`sight-engine`)

Linux tool for the two Arducam B0332 (OV9281, monochrome, global shutter) UVC cameras: discover
them, view both streams side by side, measure what they really deliver, and see what face, eye
and pupil detection make of the images. It is the v0.1 foundation for eye and head tracking.

**Status:** tested here with unit tests and with synthetic/replayed input only.
Nothing in this directory has run against the real cameras yet. The first runs are listed in
[docs/testing/hardware-test-plan.md](../../docs/testing/hardware-test-plan.md).

## Install (Ubuntu 22.04 / 24.04)

```bash
# once: uv (Python project manager) and camera tools
curl -LsSf https://astral.sh/uv/install.sh | sh        # or: pipx install uv
sudo apt install v4l-utils                              # v4l2-ctl, for cross-checking only
sudo usermod -aG video "$USER"                          # then log out and in again

git clone https://github.com/ApeDevil/lynxSIGHT.git
cd lynxSIGHT/software/diagnostic
uv sync                                  # core: OpenCV, numpy, PyYAML (Python >= 3.10)
uv sync --extra landmarks                # optional: MediaPipe face mesh + iris (recommended)
uv run sight-diag models fetch face_landmarker   # only with the extra (3.7 MB, checksummed)
uv run sight-diag doctor                 # checks GUI backend, permissions, models, cameras
```

`uv.lock` pins the versions the tests passed with (OpenCV 5.0, numpy 2.5, MediaPipe 1.2 at the
time of writing). The YuNet face model (MIT, 233 kB) is part of the repository.

## Use

```bash
uv run sight-diag list                          # cameras, capture vs metadata nodes, stable IDs,
                                                # modes (format/size/fps), controls, busy status
uv run sight-diag init-config --out exp.yaml    # config for the two detected cameras
uv run sight-diag view -c exp.yaml              # live dual view with diagnostics
uv run sight-diag bench -c exp.yaml --sweep 1280x800@30 1280x800@60 1280x800@120 640x400@120
uv run sight-diag record -c exp.yaml --phases centre:10,left:10,right:10,up:10,down:10
uv run sight-diag calibrate -c exp.yaml --grid 3x3   # experimental
```

Without a config: `view --left /dev/v4l/by-path/... --right /dev/v4l/by-path/... --mode 1280x800@60`.
Without cameras: `view --synthetic` (a generated test pattern), or point `--left`/`--right` at a
recorded `.avi`, any video file or a directory of images to replay recorded data.

### The view

Each panel shows the camera ID, state, negotiated mode, measured fps, estimated drops,
frame-interval p50/p95, driver-to-application latency, exposure/gain, image level, clipping and
a sharpness value (turn the M12 lens for the maximum). Below that, each processing function shows
its capture-to-result latency, CPU time and how many frames it skipped. Detected faces get a box
with their confidence and five landmarks, the eye regions are outlined, and the strip below the
panels magnifies every eye region pixel by pixel with the pupil estimate (circle, confidence) and
the MediaPipe iris centre (magenta ×).

Keys: `q` quit · `space` pause/resume · `r` reconnect · `s` snapshot (lossless PNG per camera +
overlay + JSON) · `tab` select camera · `[` `]` exposure −/+ (switches to manual) · `-` `=` gain ·
`a` auto/manual exposure · `o` overlays · `R` start/stop recording · `1`–`9` phase label while
recording (names from `--phases`), `0` clears it.

### Recordings

`record`, `bench` and `R` in the viewer write `experiments/<experiment_id>/<timestamp>/`:
`config.yaml` (config + negotiated modes + control values + software versions),
`frames.jsonl` (per-frame timing), `results.jsonl` (per-result latency, confidence, positions),
`events.jsonl`, `summary.json`, and with `--raw` an MJPG `.avi` + timestamps per camera that can
be replayed. `sight-diag summarize <run_dir>` recomputes the summary. Recordings stay local;
`experiments/` and `snapshots/` are git-ignored because they can contain faces.

## Stereo calibration and head-compensated gaze (experimental)

Run in this order on the rig; details and pass criteria are tests S1–S4 in the
[hardware test plan](../../docs/testing/hardware-test-plan.md).

```bash
uv run sight-diag stereo board --out board.svg             # print at 100 %, glue onto card
uv run sight-diag stereo capture -c exp.yaml               # hold the board still in ~20 poses, q solves
#   -> experiments/<id>/stereo/<time>/stereo_calibration.json (+ the view PNGs, re-solvable:)
uv run sight-diag stereo solve experiments/<id>/stereo/<time> -c exp.yaml
uv run sight-diag calibrate -c exp.yaml --grid 4x4 --screen 2048x1152 \
    --head-positions centre,left,right,up,near             # grid once per head position
uv run sight-diag gaze evaluate experiments/<id>/calibration/<time> \
    --stereo <stereo_calibration.json> --screen-mm 510x287 --above 15 --behind 10
uv run sight-diag gaze live -c exp.yaml --stereo <stereo_calibration.json> \
    --model experiments/<id>/calibration/<time>/gaze_model_head-ray_deg1.json
```

| Module | Owns |
|---|---|
| `stereo/board.py` | checkerboard spec (`9x6@25`), printable SVG, corner detection and consistent corner order |
| `stereo/calibrate.py` | intrinsics per camera (k3 fixed), outlier views, extrinsics with fixed intrinsics, `lynx-sight/stereo-calibration/v1` JSON, warnings (swapped cameras, coverage, baseline) |
| `stereo/capture.py` | live capture: a view is taken when the board is still in both cameras and differs from the views taken |
| `stereo/rig.py` | rig frame derived from the calibration (origin between the optical centres, X toward cam_right), projection, triangulation |
| `stereo/head.py` | MediaPipe landmarks of both cameras → 3-D points → head pose against the user's own face template; `iris-in-head/v1` per eye |
| `stereo/gaze.py` | `head-ray/v1`: iris-in-head → gaze angles in the head (fitted) → turned by the head pose and cast from the eye onto the screen plane |
| `stereo/evaluate.py` | offline: fit on one head position of a recorded run, test on the others, against the 2-D models |
| `stereo/live.py` | full-screen dot at the predicted gaze point |

Only the angle mapping is fitted; head movement enters through geometry. In simulation (exact
cameras, 0.3 px landmark noise, a face model with kappa offsets, not real MediaPipe output) the
head-ray model fitted with the head centred stays at ~35–50 px median per frame when the head
moves 6–10 cm or turns 12°, while the 2-D `iris-in-eye` fit grows to 130–380 px. It is
insensitive to a 25–30 mm error in the assumed screen position. The cameras are not synchronised:
landmark results of the two cameras are paired by capture time (default ≤ 20 ms apart), which is
harmless while the eyes fixate. `calibrate` now writes each run to its own timestamped directory
and keeps every MediaPipe result in `landmarks.npz` (faces as landmark coordinates, no images).

## How it works

```
camera ─► CaptureWorker (1 thread/camera) ─► FrameSlot: newest frame, shared read-only
                                               ├─► quality   ─┐
                                               ├─► face ─► eyes ├─► ResultBoard ─► view / recorder
                                               └─► landmarks ─┘
```

* Each camera is captured once, by its own thread, with a two-buffer driver queue (one buffer
  capped the cameras at ~68 of 120 fps). Frames are
  converted to 8-bit grey once (the sensor is monochrome) and shared by reference.
* Each (camera, function) pair runs in its own thread and always takes the newest frame, at most
  `max_hz` times per second; slower functions skip frames instead of queueing them, so latency
  cannot build up. Exceptions are caught per function, shown and backed off; capture and the
  other functions carry on. `eyes` runs on the exact frame `face` processed.
* Timing uses the driver's buffer timestamps when they share the host's monotonic clock (UVC
  does), so fps and gaps reflect the camera rather than Python scheduling. Drops are estimated
  from gaps longer than 1.5 frame periods; OpenCV does not expose the driver's frame counter.

| Function | What | Implementation |
|---|---|---|
| `quality` | level, p1/p99, clipped %, sharpness | numpy/OpenCV |
| `face` | face box, confidence, 5 landmarks | OpenCV YuNet (`FaceDetectorYN`) |
| `eyes` | eye regions from the landmarks, scaled by eye distance; pupil per region; roll | landmarks + `pupil.py` |
| `landmarks` | 478-point mesh, iris centres, uncalibrated head-pose angles | MediaPipe Face Landmarker (optional) |

**Choice of methods.** Haar cascades are gone from the OpenCV 5 core, give no landmarks and no
usable confidence; YuNet is small, fast on a CPU and MIT-licensed. On one test portrait
(OpenCV's 512 px sample image, not in the repository) MediaPipe put both iris centres within
about 2 px of a by-eye estimate, while the custom dark-pupil detector was 2 px off in one eye and
6 px off in the other, where it locked onto eyelashes. So MediaPipe is the recommended iris
source; the dark-pupil detector stays as a dependency-free
fallback and for the near-infrared images where MediaPipe's RGB training may not hold. Which one
works on the OV9281's images is one of the hardware tests. Head-pose angles and pupil offsets
are image measurements without camera calibration, not gaze or depth.

## Calibration engine (`sight-engine`)

The same package is the vision side of the desktop calibration app
([architecture](../../docs/architecture/desktop-calibration.md)). `sight-engine` is started by the
desktop core and speaks the versioned JSON-lines protocol of [`contracts/`](../../contracts/README.md)
on stdin/stdout; it is not meant to be run by hand (`uv run sight-engine` waits for requests).

| Module | Owns |
|---|---|
| `features.py` | per-frame gaze features: `iris-in-eye/v1` (MediaPipe corners + iris), fallback `pupil-offset/v1` |
| `baseline.py` | guided face/eye baseline (stable face, neutral reference, pose range), image measurements only |
| `calibration/targets.py` | stationary layouts and pursuit trajectories (spiral, sweeps, perimeter) at constant on-screen speed |
| `calibration/quality.py` | sample rejection: missing, low confidence, blinks (padded) |
| `calibration/alignment.py` | presentation ↔ features: settling, fixation stability, pursuit lag estimation, not-following detection |
| `calibration/model.py` | gaze model `poly2-head-linear` (reuses `poly_features`), per camera, ridge fit, contract form |
| `calibration/validation.py` | independent-target accuracy: median, RMS, p90, bias, regions, acceptance; px / mm / deg as the geometry allows |
| `calibration/recalibration.py` | quick affine correction, paired model comparison, bounded incremental offset |
| `simulation.py` | deterministic simulated user (noise, blinks, eye loss, head motion, lag, look-aways, offsets, drift, dropouts) |
| `engine/` | protocol framing, request dispatch, camera and synthetic feature sources, tracking status and guidance |

The camera path runs the diagnostic `Session` unchanged (landmarks raised to 60 Hz for
calibration) and has not run on the real cameras yet. Everything else is tested with the
simulated user, which says nothing about real accuracy.

## Develop

```bash
uv run pytest            # 116 tests; synthetic and generated data only, no camera needed
uv run ruff check . && uv run ruff format --check .
```

Testable logic lives in pure functions (V4L2 struct decoding, discovery over an injectable
sysfs tree, pupil finding, statistics, summaries, calibration fit, rendering); threads are tested
with the synthetic source. New processing functions implement `process(frame, upstream)`
(see `processing/__init__.py`) and are registered in `session.PROCESSORS` and the config defaults.

## Known limitations

* Untested on the real cameras: actual modes, frame rates with two streams on one USB 2.0
  controller, exposure units and ranges, the USB serial numbers and whether the driver's
  timestamps are usable are all unverified.
* The dark-pupil detector is basic: no IR illumination (deliberately, see the project's
  optical-safety rule), so pupil/iris contrast depends on room light.
  At 60 cm with a 70° lens, 1280 px across gives roughly 1.5 px/mm, so a 3–5 mm pupil spans only
  about 5–8 px (estimate, to be measured).
* Raw recordings re-encode to MJPG (lossy); snapshots are lossless PNG.
* The 2-D calibration is a feasibility experiment without head-pose compensation. The stereo
  head-ray model compensates head pose but is tested only in simulation; no cursor control is
  implemented (`gaze live` shows a dot).
* Stereo needs MediaPipe on both cameras at once; the head pose assumes the user faced the rig
  squarely while the face template was taken (first head position).
