# Stereo camera mount v0.1

A test fixture that holds the two Arducam B0332 cameras **clamped on the top edge of
the monitor**, looking down at the user. Desk feet are an alternative. It provides:

- a readable, lockable baseline from 70 to 160 mm,
- independent yaw and pitch for each camera, ±25°.

Everything is printed in PETG and held together with one bolt size, M4 × 16. Every
adjustment locks with a printed thumb knob, so no tools are needed.

The generator, [`hardware/mount-v0.1`](../../hardware/mount-v0.1/README.md), produces the
geometry, STLs, `.blend` file and renders. The camera dimensions it relies on, and which
of them are assumed, are in [camera-b0332.md](camera-b0332.md).

![The rig on the monitor's top edge, seen from the user's side](../../hardware/mount-v0.1/renders/assembly_iso.png)

## Coordinates and settings

These conventions are shared with the diagnostics software and are named parameters in
the generator:

- **Rig origin** is the midpoint between the two optical centres. **+X** points to the
  user's right, **+Y** up and **+Z** toward the user. `cam_left` is at −X and `cam_right`
  at +X, as seen by the user facing the cameras.
- **Baseline** is the distance between the two optical axes at the pivot plane.
- **Angles:** `yaw_deg` and `pitch_deg` are 0 when the camera looks along +Z. Positive yaw
  turns toward the rig centre. Positive pitch turns up, so **on the monitor the cameras
  use negative pitch**.
- **Pivots:** the yaw and pitch axes both pass through the assumed optical centre, on the
  lens axis 12 mm in front of the PCB. Changing an angle therefore does not move the
  optical centre, and the baseline reading holds at any angle.
- **Height:** the optical axes are **80.5 mm above the monitor's top edge**, or 79 mm
  above the desk on the feet. The camera bodies sit 12 mm in front of the screen surface.

**Is the user in view from the monitor top?** Assume the eyes are 500–700 mm from the
screen, between 150 mm below and 50 mm above the screen's top edge. The eyes are then
2.5–24.7° below horizontal from the cameras. At a pitch of about **−14°**, the 47° vertical
field of view covers that whole range with 12° to spare, and −14° is well inside the
±25° pitch range. The build computes this (`ranges.user_view_on_monitor` in the
validation report).

## Parts

| Part | Qty | Function |
|---|---|---|
| `rail` | 1 | 216 mm bar with a slot along its top, a nut tunnel inside and a key groove underneath. The top carries the baseline scale, with numbers on the back face |
| `monitor_clamp_left` / `_right` | 1 + 1 | Rest on the monitor's top edge under the rail ends. A 4 mm lip hooks over the front bezel, reaching 12 mm down. An ear beyond the rail end takes the rear arm's bolt and also stops the rail sideways |
| `clamp_arm` | 2 | Rear jaw. Its slotted bar slides along the ear, and its leg presses on the back of the monitor. It grips monitor tops **12.5–74.5 mm deep**, measured where the leg touches, and an engraved scale reads the depth at the lip's front face. Either side fits |
| `desk_foot` | 2 | *Optional*: stands the rail on a desk instead, and swaps for the clamps with the same single bolt |
| `carriage_left` / `_right` | 1 + 1 | Slide on the rail, guided by a key in the slot and locked by two knobs. Carry the yaw scale and a V notch that reads the baseline. Engraved L/R |
| `yoke_left` / `_right` | 1 + 1 | Turn on the carriage about the yaw axis, with a pointer for the yaw scale. A single arm on the outer side holds the pitch axis, so the cameras can stand close together. The arm rim carries the pitch scale |
| `camera_holder` | 2 | Hold the PCB on four standoffs with M2 screws. Rear window for the connector, cable-tie slots, and an open front so the lens can be focused. A fin reads the pitch scale. The two holders are identical |
| `knob` | 10 | Thumb knob that presses onto an M4 hex head or nut. Per camera: 2 rail locks, 1 yaw, 1 pitch. Plus 1 per rear arm |
| `coupon_pcb`, `coupon_rail`, `coupon_slider` | 1 each | Fit test, printed first |

**Every bracket attaches the same way.** The rail sits on the bracket's saddle and a boss
on the saddle keys into the rail's groove. One M4 × 16 bolt, inserted from below, goes up
through the saddle into a nut pressed into the groove ceiling.

## Bill of materials (monitor version)

| Item | Qty | Notes |
|---|---|---|
| M4 × 16 hex-head bolt, ISO 4017 / DIN 933 | 12 (+2 spare) | Per camera: 2 rail locks, 1 yaw, 1 pitch. Plus 2 bracket-to-rail and 2 rear arm. **Use hex heads, not socket heads**: the knobs grip the hex |
| M4 hex nut, ISO 4032 / DIN 934 | 12 (+2 spare) | 4 slide into the rail tunnel and 2 press into the groove pockets of the rail. 2 drop into the clamp ears, 2 sit in the yaw knobs and 2 in the holders |
| M2 × 10 screw, pan or cheese head | 8 | PCB to standoffs, from the lens side |
| M2 hex nut | 8 | Press into the back of the holders |
| Self-adhesive felt, 1.5 mm | ~ 40 × 100 mm | Under each clamp saddle, inside each lip, on each arm leg. Nothing hard touches the monitor |
| Cable tie, ≤ 3.6 mm wide | 6 | Strain relief at the holder and behind the rail |
| PETG filament | ≈ 150–200 g | Estimated from the part volumes; your slicer gives the real figure |

For the desk version, use two `desk_foot` and four rubber bumpers instead of the clamps,
arms, felt and their four bolts and nuts.

No washers are needed. The knob pockets are shallower than the head or nut, so the steel
bears on the part and the knob only turns it. The generator checks every M4 stack-up:
each has full nut engagement and room for the bolt tip.

## Printing on the Bambu Lab P2S (PETG, 0.4 mm nozzle)

The P2S build volume is **256 × 256 × 256 mm** ([manufacturer spec via retailer][p2s1],
[second listing][p2s2]). The build checks every part against that volume, keeping 5 mm
inside each edge. The largest part is the rail at 216 × 28 × 22 mm, and the next is a
desk foot at 30 × 135 mm.

[p2s1]: https://www.gigaparts.com/bambu-lab-p2s-3d-printer.html
[p2s2]: https://www.makerpoint.nl/en-gb/3d-printing/3d-printers/bambu-lab-all/bambu-lab-p2s-210000007716

**Ready-made plates.** Open the files in `hardware/mount-v0.1/plates/` in Bambu Studio,
in this order:

| Plate | Contents | Use |
|---|---|---|
| `1-coupons.3mf` | `coupon_pcb`, `coupon_rail`, `coupon_slider`, 1 knob | Check the fit first (next section) |
| `2-mount.3mf` | The whole monitor rig: rail, both clamps, 2 clamp arms, both carriages, both yokes, 2 camera holders, 10 knobs | Everything else, in one print |

The generator nests parts by their real footprints, not their bounding boxes, so knobs
fill the corners of the L-shaped clamp arms. Each part is a separate object, already in
its print orientation and at least 8 mm from its neighbours and 5 mm from the bed edge, so don't rotate or re-arrange anything. On a whole plate, the simplest choice is the
stronger setting below (4 walls, 30 % gyroid) for every part.
Desk feet are not on a plate. Print `stl/desk_foot.stl` twice if you want them.

No part needs supports. Each STL is exported lying in its print orientation, centred, on
z = 0. Start from Bambu Studio's **Generic PETG** (or your filament's) profile on the
textured PEI plate, and change only:

| Setting | Value |
|---|---|
| Layer height | 0.2 mm |
| Walls | 4 for yokes, knobs, holders, clamps and arms; 3 elsewhere |
| Infill | 30 % gyroid for yokes, holders, knobs, clamps and arms; 20 % for the rail and carriages |
| Supports | Off |
| Elephant-foot compensation | 0.15 mm (the yaw scale is on the carriage face that prints on the plate) |

| STL | Orientation (already applied) |
|---|---|
| `rail` | Underside down; the tunnel, groove and nut pockets print as short bridges |
| `monitor_clamp_*` | Front face of the lip on the plate. The key boss has a 45° back, and the horizontal holes are teardrops |
| `clamp_arm` | Flat, depth scale up |
| `desk_foot` | Pad down |
| `carriage_*` | Upside down: key up, scale face on the plate |
| `yoke_*` | Base down; pitch hole is a teardrop |
| `camera_holder` | Rear plate down; fins have 45° undersides; pitch hole is a teardrop |
| `knob` | Hex pocket up |

## First print: the fit coupons (about 1 hour)

Print `coupon_pcb`, `coupon_rail`, `coupon_slider` and one `knob` together, then check:

1. **PCB on `coupon_pcb`:**
   - The camera sits flat on the four standoffs, with M2 × 10 screws into M2 nuts
     pressed into the back pockets.
   - If the board has no holes on the 34 mm square, try the 28 mm through-holes and
     report which pattern exists.
   - Nothing on the back of the PCB touches the plate: the standoffs are 5 mm and the
     window is 26 × 26 mm.
2. **Pitch joint on `coupon_pcb`:** an M4 nut presses into the side pocket, and a bolt
   goes through the teardrop hole and threads into it.
3. **`coupon_rail`:**
   - An M4 nut slides through the tunnel without spinning.
   - A nut presses into the hex pocket in the groove ceiling.
   - `coupon_slider` drops into the slot and slides with light friction.
   - Bolt the slider down with a knob and M4 × 16 into the tunnel nut. It must clamp
     firmly, and the bolt tip must not stick out of the tunnel.
4. **Knob:** presses onto an M4 head and onto a nut, and does not slip when tightened by
   hand.

If a fit is off, change the matching FIT value in `params.py` and rebuild.

## Assembly

1. **Rail nuts:**
   - Press one M4 nut into the hex pocket at each end of the groove under the rail.
   - Slide two M4 nuts into each end of the rail tunnel.
2. **Clamps:**
   - Stick felt under each clamp saddle and inside each lip.
   - Drop an M4 nut into the slot in each ear.
   - Set the rail on the two saddles, with the boss in the groove and the rail ends
     against the ears.
   - Bolt each clamp on from below: an M4 × 16 with its head in the saddle pocket, up
     into the groove nut.
3. **Carriages:**
   - Set each carriage on the rail with its key in the slot, L on the user's left.
   - Push M4 × 16 bolts through two knobs and the carriage into the tunnel nuts, and
     snug them.
4. **Yokes:**
   - Drop an M4 × 16 into the hex pocket on top of the yoke base.
   - Set the yoke on the carriage with its arm on the outer side.
   - Under the carriage, press a nut into a knob and thread it on.
5. **Cameras:**
   - Press M2 nuts into the back of the holder.
   - Screw the PCB on from the lens side.
   - Press an M4 nut into the inner pocket of the wall that will face the yoke arm.
6. **Holders:** hold each one in its yoke, and bolt it through the arm with a knob and an
   M4 × 16.
7. **On the monitor:**
   - Stick felt on each arm leg's inner face.
   - Hang the rig on the top edge with the lips over the front bezel, centred on the
     screen.
   - Put each arm on its ear with the leg behind the monitor, and its bolt and knob
     through the slot into the ear nut.
   - Slide each arm forward until the felt touches, then tighten. The depth scale on the
     bar, read at the lip's front face, gives the setting for next time.
8. **Cables:**
   - Plug in USB and tie the cable to the slot pair on the holder's rear plate, leaving a
     loose loop for yaw and pitch.
   - Run it down behind the carriage, and tie it at the slot pair on the clamp saddle
     behind the rail.
   - Let it hang down the back of the monitor.

## Setting and reading the adjustments

| Adjustment | Unlock | Read |
|---|---|---|
| Baseline | the two knobs on the carriage | The V notch in the carriage's back edge against the rail scale, read from behind. With both carriages on the same mark, that mark *is* the baseline. Ticks every 5 mm, numbers every 20 mm, long tick at 100 |
| Yaw | the knob under the carriage | The yoke pointer against the carriage ticks: every 5°, long every 10°. The dimple marks **positive**, toward the rig centre |
| Pitch | the knob on the yoke arm | The front face of the holder's fin against the ticks on the arm rim. The dimple marks **positive**, up; on the monitor you will use the other side |
| Monitor depth | the knob on each rear arm | The tick on the arm's bar at the lip's front face: every 10 mm, long every 20 mm |

Hold the camera while tightening yaw or pitch. Record settings as
`baseline, cam_left yaw/pitch, cam_right yaw/pitch`.

## What has been verified, and how

**CAD-level checks.** These ran in the cloud with Blender 5.2.3 through `build.py`, and
the results are in [`validation/report.json`](../../hardware/mount-v0.1/validation/report.json):

- **Meshes:** all 14 printable meshes are closed, manifold, single bodies with positive
  volume, and fit the P2S volume with a 5 mm margin.
- **Overhangs:** the only faces steeper than 45° are inside engraved numbers and letters:
  ≈ 28 mm² on the rail and 0.6 mm² on the "R" of the right carriage. Everything else is a
  bridge over a hole, groove or channel.
- **Camera fit:** the reference camera, with its assumed dimensions, does not overlap the
  holder.
  - PCB: 1 mm side clearance, seated on the standoffs.
  - Lens: ≥ 8.5 mm from the holder.
  - Rear parts: ≥ 0.5 mm from the holder.
- **Motion:** 585 poses found no collisions between any parts, cameras, or the monitor
  stand-in. The sweep covers:
  - the desk stand, and the monitor clamp at both its thinnest (12.5 mm) and thickest
    (74.5 mm) setting,
  - baselines 70, 100 and 160 mm,
  - yaw −25…+25° in 5° steps,
  - pitch −25…+25° in 12.5° steps,
  - both cameras turned the same way and opposite ways.

  A self-test confirms that the checker catches a deliberate overlap.
- **Connector access:** the USB plug-and-cable keep-out hits no other part in any pose.
- **Field of view:** the monitor never enters the image. Only the clamp's rear arm does,
  at −25° pitch with −25° yaw (looking down and outward), a setting that is not used
  when looking at the user. The trimmed carriage front no longer enters any image.
- **User in view:** see *Coordinates and settings* above.
- **Fasteners:** every M4 joint fully engages its nut (3.2 mm), and every bolt tip has
  room.

**Not verified (needs hardware):**

- Every camera dimension marked ASSUMED, in particular the hole pattern, rear component
  height, connector position and optical centre.
- Printed tolerances: press fits, key slide, teardrop holes.
- Lock holding torque, scale repeatability and accuracy.
- Stiffness on the monitor:
  - whether typing or touching the monitor shakes the image,
  - whether the clamp shifts on a glossy or curved top edge,
  - whether the lip covers any pixels on your monitor's bezel.
- Fit on your monitor: the top-edge depth at the leg's height, and whether the back is
  flat enough there for the leg.

## Physical tests to run

1. **The coupons above.** Report the hole pattern, the pocket fits and the rail clamp.
2. **Camera measurements** listed in [camera-b0332.md](camera-b0332.md).
3. **Your monitor:**
   - top-edge thickness at 0, 20 and 40 mm below the top, front to back;
   - bezel height above the first pixel row;
   - whether the top edge is flat.
4. **Clamp:** hang the rig, tighten the arms, then tap the rig sideways and forward. It
   must not shift or tip.
5. **Baseline scale:** set 70, 100 and 160 mm. Measure between the lens barrel centres
   with calipers; the error should be under 1 mm.
6. **Angles:** check pitch at 0 and −20° with a phone inclinometer on the holder back,
   and yaw against a printed protractor.
7. **Repeatability and stability:**
   - Set, disturb and reset an angle five times, recording an image each time.
   - Watch the live preview while typing and while touching the monitor.

## Known limitations of v0.1

- **Hole pattern:** the holder has standoffs only on the 34 mm square. A board with only
  the 28 mm set needs one parameter changed.
- **Baseline scale:** it is read from behind the rig.
- **Height:** it is fixed at about 80 mm above the monitor top. There is no riser.
- **Pitch arm:** it is single-sided, chosen to reach the 70 mm minimum baseline. It is
  stiff enough on paper but untested.
- **Clamp grip:** the clamp holds by the felted lip and the rear arm. Very thin or
  strongly curved monitor tops (< 12.5 mm deep where the leg touches) are out of range.
