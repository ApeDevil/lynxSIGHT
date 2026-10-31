# Fixed camera rig v0.1: geometry check and first camera test

Checked on 2026-10-31 from `hardware/mount-v0.1/blend/camera-rig-v0.1.blend` (object `rig`,
read headlessly with Blender 5.2.2). Nothing in the .blend was changed. Camera dimensions and
their confidence come from [camera-b0332.md](camera-b0332.md); nothing has been measured with
calipers yet, so every fit statement below is a prediction until the first print.

## 1. What the rig is

One solid part, mirrored about X = 0 (Mirror modifier), mesh closed and manifold.

| Feature | Blender coordinates (mm, Z up, user on the −Y side) |
|---|---|
| Bar | X −150…150, Y −10…10, Z −5…5 (300 × 20 × 10) |
| Inner post (each side) | \|X\| 107.16…111.30, full depth, up to Z 43.13 |
| Outer post (each side) | \|X\| 145.30…150.00, full depth, up to Z 43.13 |
| Window between posts | 34.00 wide (\|X\| 111.30…145.30), 38.13 tall above the bar |
| PCB slot | \|X\| 109.36…147.50 (38.14 wide), Y 0.76…3.33 (2.57 thick), open at the top |

The PCB stands vertically in the slot, resting on the bar top, lens toward −Y (toward the user),
USB connector toward +Y. That matches the orientation of the old mount in the same file.

## 2. Camera positions

Assuming the lens axis is at the PCB centre (ASSUMED) and the optical centre is 12 mm in front of
the PCB face (ASSUMED):

| | Blender (X, Y, Z) | Rig frame (X right, Y up, Z toward user) |
|---|---|---|
| `cam_left` (user's left) | (−128.4, −11.2, 24.0) | (−128.4, 0, 0) |
| `cam_right` | (+128.4, −11.2, 24.0) | (+128.4, 0, 0) |
| Yaw / pitch | 0° / 0° (parallel axes, level) | 0° / 0° |
| Bar underside | Z −5 | Y −29 (optical axes are 29 mm above the surface the rig stands on) |

**Baseline: 256.9 mm** (slot centres; 256.6 mm between the window centres). Set
`rig.baseline_mm: 257` in the experiment config.

What that baseline means with the 70° lens (ideal-lens estimates, focal length ≈ 914 px at
1280 px width):

| | 50 cm | 60 cm | 70 cm |
|---|---|---|---|
| Face centre offset from each image centre | 14° / 234 px | 12° / 196 px | 10° / 168 px |
| Stereo disparity | 470 px | 391 px | 335 px |
| Depth change per 1 px disparity | 1.1 mm | 1.5 mm | 2.1 mm |
| Width seen by both cameras | 443 mm | 583 mm | 723 mm |
| Vertical field (±23.6°) | ±218 mm | ±262 mm | ±306 mm |

Both cameras see the centre line from 18 cm outward, so parallel axes work: no toe-in is needed.
The wide baseline gives good depth resolution; the price is that each camera sees the face from
about 12° to the side, so at strong head turns the nose can hide the far eye from one camera.

## 3. Findings

| # | Finding | Effect | Suggestion |
|---|---|---|---|
| 1 | Slot is 2.57 mm thick for a 1.6 mm PCB (ASSUMED) | ~1 mm play: the board can lean ±1.5° and shift 1 mm, so the camera position is **not** repeatable | 1.9 mm (0.3 mm play) after measuring the PCB, or a printed wedge/clip |
| 2 | Slot is 38.14 mm wide for a 38.0 mm PCB | 0.07 mm per side; FDM slots print narrow, so the board will probably not slide in | 38.4–38.5 mm, or print a 10 mm tall test piece of one post pair first |
| 3 | The posts cover the outer 1.9 mm (inner) and 2.2 mm (outer) of the board edges, front and back | Any component in those strips blocks the slot (the 34 × 34 hole pads are flat and fine) | Check both faces of one camera before printing |
| 4 | Slot is 0.12 mm off-centre in the window (notch depths 1.95 vs 2.20 mm); coordinates like 43.128 and 0.759 look scaled rather than typed | Harmless, but makes the numbers hard to reason about | Round to clean values when you revise it |
| 5 | Object `rig` has unapplied scale (0.15, 0.01, 0.005) on a ±1000 mesh | Fine in Blender; can confuse exporters and later edits | Ctrl+A → Scale before exporting the STL |
| 6 | Pitch is fixed at 0° | The face must be within about ±26 cm of camera height at 60 cm, or it leaves the frame | Put the rig at eye height (top of the monitor) or prop the front up for now |
| 7 | Nothing holds the board from above, no cable strain relief, no monitor/desk attachment | A cable tug lifts the camera out | Expected for a first prototype; add with the extension |

## 4. Printer fit (Bambu Lab P2S, 256 × 256 mm)

The bar does not fit straight (300 > 256) but fits diagonally: a 300 × 20 mm footprint at 45°
needs (300 + 20)/√2 = **226 mm** along each bed axis, leaving 30 mm. Print it standing on the bar
underside, posts up (48 mm tall); the slots then print vertically, which keeps them accurate.

If you want the longest bar: the theoretical limit for a 20 mm wide bar is 256·√2 − 20 =
342 mm; with 5 mm kept clear of the bed edges about **325 mm**. Whether Bambu Studio allows the
extreme corners of the P2S bed has not been checked.

## 5. First camera test (on the Ubuntu workstation)

Expected outputs below are predictions. Nothing has run against the real cameras yet; record
what you actually see in [hardware-test-plan.md](../testing/hardware-test-plan.md).

**Step 0 — one-time setup.** Your user is not in the `video` group yet (checked with
`sight-diag doctor` on 2026-10-31). Add it, then log out and back in:

```bash
sudo usermod -aG video "$USER"
sudo apt install v4l-utils
cd ~/dev/lynxSIGHT/software/diagnostic
uv sync --extra landmarks
uv run sight-diag models fetch face_landmarker
```

**Step 1 — plug in.** Use two USB ports, ideally on different USB controllers (front and back of
the PC), no unpowered hub. Two MJPG streams usually fit on one USB 2.0
controller at moderate frame rates, but at 120 fps they may not (unmeasured).

```bash
lsusb                    # expect two identical camera lines (name may say Arducam or the chip vendor)
lsusb -t                 # expect each camera under a different "Bus" if they are on separate controllers
v4l2-ctl --list-devices  # expect each camera with two /dev/videoN nodes (capture + metadata)
```

**Step 2 — doctor (H1).**

```bash
uv run sight-diag doctor
```

Expect `user in 'video' group: yes`, `GUI backend: yes`, both models found and
`capture cameras: 2 (2 look like Arducam/OV9281)`.

**Step 3 — list (H2, H4).**

```bash
uv run sight-diag list
```

Expect both cameras once each, a `/dev/v4l/by-path/...` link per camera, and a mode table with
MJPG 1280 × 800 at up to 120 fps and the exposure/gain controls. Note whether the serial numbers
are identical or missing (common for these boards): then the USB port identifies the camera.

**Step 4 — config (H7).**

```bash
uv run sight-diag init-config --out exp.yaml
```

Open `exp.yaml` and set `rig.baseline_mm: 257` and `rig.user_distance_mm` to your measured eye
distance.

**Step 5 — one camera first (H6).** Copy a by-path from step 3:

```bash
uv run sight-diag view --left /dev/v4l/by-path/<camera-1> --mode 1280x800@60
```

Expect a grey (monochrome) live image and a measured fps close to 60. If it is blurry, see step 7.

**Step 6 — both cameras (H7).**

```bash
uv run sight-diag view -c exp.yaml
```

Expect two live panels. Cover the camera on **your** left with your hand: the `cam_left` panel
must go dark. If the other one does, swap the two `device:` lines in `exp.yaml`. Your face should sit about 200 px toward the rig centre
in each image at 60 cm (section 2). Press `s` for a snapshot, `q` to quit.

**Step 7 — focus (H11).** The lenses are factory-focused for 1 m to infinity. Hold printed text at
60 cm, turn each M12 lens slowly and stop where the panel's `sharp` value peaks.

**Step 8 — frame rate with both streams (H8).**

```bash
uv run sight-diag bench -c exp.yaml --sweep 1280x800@30 1280x800@60 1280x800@120 640x400@120 --json-out bench.json
```

The key result is the highest mode where both cameras show under 1 % drops. If 1280 × 800 @ 120
drops frames, the cameras probably share a USB controller (step 1).

**Step 9 — face and eyes (H12).** Sit at 50–70 cm, room light, run `view -c exp.yaml` again.
Expect a face box with five points in both panels and the eye tiles showing your eyes. Snapshots
contain your face: they stay in the git-ignored `snapshots/` folder.

**If something fails:** `No V4L2 video devices found` → cable or port (check `lsusb`).
`Permission denied` → step 0, log out and in. `busy` → close Cheese, OBS or a browser tab using
the camera. Black image → press `a` for auto exposure or `]` to raise exposure.
