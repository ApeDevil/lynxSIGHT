# Camera diagnostic: hardware test plan (v0.1)

What has to be run on the Ubuntu workstation with both Arducam B0332 cameras connected, because
the cloud build has no cameras. Everything below is **unverified** until a run's results are
recorded in the table at the end.

Setup for all tests: `cd software/diagnostic`, `uv sync --extra landmarks`,
`uv run sight-diag models fetch face_landmarker`. Record the Ubuntu version, kernel
(`uname -r`), the USB ports used and whether the two cameras share a USB controller
(`lsusb -t`).

| # | Test | Command | Pass when | Record |
|---|---|---|---|---|
| H1 | Environment | `uv run sight-diag doctor` | GUI backend yes, user in `video` group, YuNet found | output |
| H2 | Discovery | `uv run sight-diag list` and `v4l2-ctl --list-devices` | both cameras listed once each, as `capture` + `metadata` nodes, with by-path links; flagged as candidates | full `list --json` output (attach) |
| H3 | Identity | unplug one camera, run `list`; replug into the same port | the remaining camera keeps its by-path; serials noted (identical/absent?) | serials, by-path links |
| H4 | Modes and controls | from H2 output | MJPG/YUYV sizes and rates listed; `exposure_time_absolute`, `auto_exposure`, `gain` (names may differ) present | mode table, control ranges |
| H5 | Busy detection | open a camera in `cheese` or `guvcview`, then `list` | that camera shows `busy (in use by …)`; `view` reports busy instead of hanging | message text |
| H6 | Single stream | `uv run sight-diag view --left <by-path> --mode 1280x800@60` | image visible, fps close to request, no errors | fps, drops, drv-lat |
| H7 | Dual stream | `uv run sight-diag init-config --out exp.yaml`, then `view -c exp.yaml` | both live; cam_left really is the user's left (swap in exp.yaml if not) | screenshot via `s` |
| H8 | Throughput sweep | `uv run sight-diag bench -c exp.yaml --sweep 1280x800@30 1280x800@60 1280x800@120 640x400@120 YUYV:640x400@60 --json-out bench.json` | table printed for every mode, both cameras | `bench.json` (key result: highest mode with < 1 % drops on both) |
| H9 | Exposure | in `view`: `[`/`]`, `a`, `-`/`=` on each camera | brightness responds; manual exposure holds; fps drops when exposure exceeds the frame period | control ranges, units observed |
| H10 | Reconnect | in `view`: unplug a camera for 5 s, replug | panel shows error, then recovers by itself (or with `r`); other camera unaffected | time to recover |
| H11 | Focus | point at text at 60 cm, turn each M12 lens | `sharp` value peaks at best focus | peak values |
| H12 | Face and eyes | sit at 50–70 cm under the monitor, normal room light | face box + 5 landmarks stable; eye tiles show the eyes; note pupil confidence and magenta iris cross | snapshots (`s`), personal data: keep local |
| H13 | Head-position experiment | `uv run sight-diag record -c exp.yaml --phases centre:10,left:10,right:10,up:10,down:10,near:10,far:10` | `summary.json` has per-phase detection rates | `summary.json` |
| H14 | Processing load | `bench -c exp.yaml --sweep 1280x800@60 --process` | fps without processing ≈ with processing; note processor latencies | `bench.json`, CPU model |
| H15 | Calibration (experimental) | `uv run sight-diag calibrate -c exp.yaml --grid 3x3` | completes; `calibration.json` has train/LOO RMSE | RMSE values |
| H16 | Lighting | repeat H12 with a desk lamp off/on, window light | where detection breaks down | notes |

Questions the tests answer, needed before choosing the tracking approach:

1. Which mode both cameras sustain together without drops (the advertised 120 fps is per camera
   and depends on mode).
2. Whether YuNet and MediaPipe work on the OV9281's monochrome, IR-sensitive images.
3. How many pixels the pupil and iris span at 50–70 cm (estimate: pupil 5–8 px, iris about
   18 px at 1280 px width).
4. Whether the driver timestamps are on the monotonic clock (`drv-lat` shows a small positive
   number of milliseconds; `-` means they are not used).

## Results

| Date | Test | Result | Notes |
|---|---|---|---|
| 2026-10-31 | H1 | partial | Ubuntu, kernel 7.0.0-42. GUI backend yes, both models found. `video` group added but session not re-logged; cameras still open via the seat ACL |
| 2026-10-31 | H2 | pass | Both cameras found once each as capture + metadata nodes, USB 0c45:6366 "Arducam OV9281 USB Camera", both in ports 3-6.3 / 3-6.4 behind one Genesys USB 2.0 hub |
| 2026-10-31 | H3 | partial | Both cameras report the **same serial `UC762`**: identity must come from the by-path link (USB port) |
| 2026-10-31 | H4 | pass | MJPG 1280x800 @120/100, 1280x720 @120, 800x600/640x480/320x240 @120/100; YUYV 1280x800 and 1280x720 @10 only. No 60 fps mode (a 60 request negotiates 100). exposure_time_absolute 1-5000 (default 157), gain 0-100, auto_exposure 1 = manual / 3 = auto, power_line_frequency default 60 Hz |
| 2026-10-31 | H8 | inconclusive | Both cameras ~57-68 fps at every mode, p95 interval 20 ms, <1 % drops, also with a single camera and with 5 ms manual exposure. Run while an unrelated Blender job held all 24 cores at 99 %, so CPU starvation is not ruled out. Two streams on the shared hub gave ~200 "Corrupt JPEG" warnings per 6 s; one camera alone gave 1. Repeat on an idle machine with the cameras on different USB controllers |
| 2026-10-31 | H8 (repeat) | inconclusive | cam_left moved to root port 3-1 (same controller, no hub); cam_right stays at 3-6.4. Corrupt JPEG warnings 0 (was ~200). Still ~67-68 fps at 1280x800@120 and 640x480@120, <0.3 % drops, Blender still at 98 % CPU |
| 2026-10-31 | H8 (idle) | camera pass, app limited | Idle PC (~10 % CPU): sight-diag still ~57-68 fps on both cameras, 0 drops, 0 corrupt frames. A bare OpenCV grab loop without decoding gets **120 fps** at 1280x800 from cam_right, with auto exposure and with manual exposure 157. So the cameras deliver 120 fps; the limit is sight-diag's per-frame `cap.read()` (MJPEG decode to BGR, then grey) in the capture thread |
| 2026-10-31 | H6/H7 | pass (user report) | `view -c exp.yaml` shows both cameras live. Left/right assignment and per-camera fps from the view not yet recorded |
| 2026-10-31 | H12 | pass (user report, first look) | Face detected (green box) and both eye regions outlined (cyan) in room light. Pupil confidence, iris cross, distance and stability not yet recorded; no snapshots kept |
| 2026-11-01 | H2 | pass | Rig v0.3.x on the monitor. Both cameras again in 3-6.3 / 3-6.4 behind the Genesys hub (05e3:0608), same modes as 2026-10-31 |
| 2026-11-01 | H8 (root cause) | pass after fix | Near-idle PC (load ~1-2, Ryzen 9 3900X). The ~68 fps cap is the **one-buffer driver queue** (`capture.buffer_size: 1`), not decoding: a bare grab+decode loop on both cameras at once gives 68.2 fps with `CAP_PROP_BUFFERSIZE` 1 and 120.5 fps with 2 or 3, at auto exposure (157) and manual 50/80. 640x480@120 was also capped at 68 with one buffer. Default changed to 2 buffers and 120 fps |
| 2026-11-01 | H8 | pass | `bench -c exp.yaml` (MJPG 1280x800@120, 2 buffers), 10 s: both cameras 120.6-120.7 fps, 0 % drops, p95 interval 12.0 ms, **0 corrupt-JPEG warnings with both cameras on the shared hub**. The 2026-10-31 corruption was probably the CPU-starved run |
| 2026-11-01 | H14 | pass | `bench --process`, 15 s, all four processors: 119.9-120.0 fps, 1.0-1.1 % estimated drops. Face detect rate 1.00 on both (score 0.89 / 0.87), YuNet 12-13 ms CPU, landmarks 8-14 ms, capture-to-result p95 23-30 ms, 0 processor errors. cam_left (3-6.3) face centre x 0.44, eye distance 52 px, sharpness 47; cam_right (3-6.4) face centre x 0.18, eye distance 38 px, sharpness 25 (L/R not yet confirmed physically; framing and focus pending) |
| 2026-11-01 | H7/H12 | partial (user report) | After replugging the cables to the intended sides (ports unchanged: 3-6.3 / 3-6.4): whole head and both eyes inside both camera pictures. Panel-to-lens check (cover test) and focus values not yet recorded |
| 2026-11-01 | H7 | pass (user report) | Cover test: covering the user's left lens darkens the left panel, right lens the right panel. cam_left = port 3-6.3, cam_right = 3-6.4 as in exp.yaml. Lenses refocused by the user by eye in the view |
| 2026-11-01 | H12/H14 | pass | After L/R fix and refocus, user seated normally, room light, 15 s `bench --process`: 120.4 fps both, 0.3 / 0.5 % est. drops, 0 corrupt JPEG. Face detect 1.00 both (score 0.90), pupil found 1.00 both, eye distance 83 px both. Face centre (x, y) left 0.29, 0.71 / right 0.55, 0.65: face sits below image centre in both, so a few degrees of downward pitch would centre it. Mean sharpness left 39 / right 60 (scene-dependent, not a focus verdict on its own); image level 81 / 87 of 255. Landmark capture-to-result p95 26-30 ms |
| 2026-11-01 | H15 | fail (method) | `calibrate -c exp.yaml --grid 3x3`: ran to completion, all 9 targets got samples (680 pupil samples), but train RMSE 208 px and LOO RMSE 954 px, i.e. unusable. Causes seen in samples.jsonl: (1) screen auto-detected as 1152x1152 under Wayland; real displays are 2048x1152 (HDMI-2, primary) and 1920x1080 (HDMI-1), so targets were drawn on a wrong square layout; (2) the fit pools both cameras and both eyes into one mean per target, and which camera/eye gave a confident pupil changed from target to target, so the means jump; (3) dark-pupil offsets moved only ~0.1 (eye-region units) across the whole screen against ~0.02-0.03 per-target SD. Next: rerun with `--screen`, fit per camera and eye, or use the iris-in-eye features of sight-engine |
