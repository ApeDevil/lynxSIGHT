# Camera rig v0.2: threaded fastening and review

Source: `hardware/mount-v0.1/blend/camera-rig-v0.2.blend`, collection `test-2` (left untouched).
Output: `camera-rig-v0.2.1.blend`, new collection **`test-2 threaded`** (the original `test-2` is only hidden in the viewport of the new file).
All numbers are measured from the CAD; nothing here has been printed or fitted.

## 1. Fastening screw and threads (done)

How the clamp works, as modelled: the rig's rear stem has a horizontal through-slot (6.8 mm tall, y 11.75–136.6 mm). The fastening hangs down behind the monitor, its tab slides in the slot, and a knob screw from the other side pulls the fastening against the stem. Sliding it along the slot sets the monitor depth (about 18–135 mm).

Problem found: the old 8 mm screw cannot pass the 6.8 mm slot, and the 5 mm tall tab is too small to hold any useful thread.

Change:

| | v0.2 (yours) | v0.2.1 |
|---|---|---|
| Thread | 8 mm, pitch 2 | **6 mm, pitch 1.5**, 45° flanks (same family as v0.1, prints without support) |
| Screw | 18 mm knob, 14.5 mm shank | **14 mm knob × 6 mm, 19.5 mm shank**, chamfered tip |
| Screw in slot | 8 mm in 6.8 mm slot (does not fit) | 6 mm in 6.8 mm slot, 0.4 mm per side |
| Fastening plate | 4.15 mm thick | **8 mm thick** (outward only; inner face, size and position unchanged) |
| Threaded hole | none | through the plate, 6.6 mm tap (0.3 mm radial clearance), 45° lead-in both ends |
| Key in slot | one 5 × 10.2 mm tab | **two ribs 2.4 × 6.4 mm**, either side of the screw, 0.2 mm per side in the slot; they stop the fastening twisting |
| Thread engagement | – | 7.5 mm (5 turns) when tight, 6.25 mm before tightening |

Checks run (CAD only): both new parts are closed manifold solids; no interference with the rig (the knob face sits on the stem face); the screw ends 0.5 mm inside the plate.

Print: `fastening_threaded.stl` lies on its outer face, ribs up, hole vertical (48.9 × 13.4 × 13.6 mm). `screw_fastening_6mm.stl` stands head down (14 × 14 × 25.5 mm). Use the v0.1 rule for screws: 6 walls, 100 % infill. 6 mm is the smallest printed thread I'd trust on a 0.4 mm nozzle; print one screw and the fastening first and check that it turns by hand.

## 2. Review: problems found

Ordered by how much they block a working print.

1. **PCB slot in the camera frame is too narrow.** Slot floor to floor is 37.29 mm; the board is 38 mm (manufacturer). The board will not go in. Needs ≥ 38.3 mm (slot floors at ±19.15 from the frame centre), which leaves only 1.7 mm of outer wall in the 4.14 mm upright, so widen the uprights by ~1 mm outward too.
2. **The stem slot needs support.** With the rig printed flat, the top strap of the stem is a 125 mm unsupported span over the slot. Either print with support inside the slot (open on both sides, so it pulls out) or turn the slot vertical (through the top) with a vertical screw, which prints with no support at all. I'd recommend the vertical slot.
3. **The stem is two 1.6 mm straps.** Stiff enough lengthwise, but thin and the knob clamps on their 1.6 mm edges. A 12 mm tall stem would give 2.6 mm straps at the same slot height.
4. **Frame tabs are loose in the rig pockets.** 0.28 mm per side across x and 0.23–0.32 mm in y. Over the 37.4 mm between the two tabs this allows about 0.8° of yaw per camera, enough to spoil a stereo calibration if a frame gets knocked. 0.1 mm per side, or a dab of glue after calibration, fixes it.
5. **Thin wall at the outer rig ends.** The outer pocket stops 0.75 mm from the end of the bar (x 148.09 vs 148.84): about two perimeters, and it will crack. Extend the bar ends by 2 mm or move the pockets inward.
6. **PCB slot is 2.57 mm for a 1.6 mm board.** About 1 mm of play, so the camera can tilt. ~1.9 mm is enough (board thickness 1.6 is assumed, not measured).
7. **Rear component envelope touches the uprights.** The assumed 37 × 37 × 3 mm rear-parts box overlaps the upright behind the slot by up to 1.8 mm. This is an assumption, not a measured part: check against the real board.
8. **Rig mesh has an internal face** where the front lip meets the mirror plane at x = 0 (4 non-manifold edges after the mirror). Slicers usually cope, but deleting that face makes it clean.
9. The front lip reaches only 3.4 mm below the monitor top, so it holds only if your bezel has an edge there. Still waiting on bezel height.

## 3. Review: what is fine

- **Baseline 256.0 mm** (lens centres x = ±128.0). The software config uses 257: update it or measure.
- Both cameras are mirrored, so lens axes are parallel and level by construction, pointing −Y. Lens axis 19.0 mm above the rig top.
- Nothing is in the field of view: frames and bar sit behind the lens front (y −20.6).
- USB connectors face backwards into open space, so cables can come out.
- Assembly order works: board slides up into the frame from below, the top bar stops it, then the frame tabs drop into the rig pockets and the rig top holds the board in.
- The whole T (297.7 × 148.3 mm) fits the P2S bed at 45°: 224.6 × 224.6 mm, 15 mm spare each side.
- The original `screw_fastening` sat 0.64 mm off the fastening centre in y; the new screw is on the centre (y 80.165).

## 4. Still unverified (needs you)

- Print the screw and fastening and check that the thread turns by hand and holds.
- Fix the PCB slot width (item 1) before printing a frame; I didn't change the frames, only reported them.
- Measure the board thickness and rear component height, and confirm baseline and lens height after assembly.
