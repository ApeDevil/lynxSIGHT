# LYNX SIGHT diagnostic (`sight-diag`)

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

## How it works

```
camera ─► CaptureWorker (1 thread/camera) ─► FrameSlot: newest frame, shared read-only
                                               ├─► quality   ─┐
                                               ├─► face ─► eyes ├─► ResultBoard ─► view / recorder
                                               └─► landmarks ─┘
```

* Each camera is captured once, by its own thread, with a one-buffer driver queue. Frames are
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

## Develop

```bash
uv run pytest            # 59 tests; synthetic and generated data only, no camera needed
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
* The calibration is a feasibility experiment (polynomial fit without head-pose compensation);
  no cursor control is implemented.
