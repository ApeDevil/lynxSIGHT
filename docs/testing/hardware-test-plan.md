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
| | | | |
