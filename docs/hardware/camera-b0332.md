# Arducam B0332 — mechanical reference for mount v0.1

The camera holder is built around the dimensions below. Most of them are **not published
by Arducam** and have not been measured yet, so each one is tagged with its source. The
values live in [`params.py`](../../hardware/mount-v0.1/lynx_mount/params.py) (`Camera`),
where the tag is part of the value.

| Tag | Meaning |
|---|---|
| **MFR** | Stated by Arducam (product page, manual) |
| **ASSUMED** | Typical for 38 mm Arducam UVC boards and M12 lenses; not verified for our units |
| **MEASURED** | Taken from our cameras with calipers. No dimension has this tag yet |

## What the manufacturer states

| Item | Value | Source |
|---|---|---|
| Board | 38 × 38 mm | [Arducam product page][product], [B0332 manual][manual] |
| Mounting holes | "Hole pitch compatible with 34 × 34 mm, 28 × 28 mm" | [product page][product] |
| Lens mount | M12 × P0.5, manual focus; the lens is described as not interchangeable | [manual][manual], [product page][product] |
| Field of view | 70° horizontal | [product page][product] |
| Factory focus range | 1 m to infinity | [product page][product] |
| Connector | USB 2.0 connector on the back; type and position not stated | [manual][manual] |
| Cable | 1 m | [product page][product] |
| 3D model | A STEP file is mentioned but no download link is published | [product page][product] |

[product]: https://www.arducam.com/product/arducam-120fps-global-shutter-usb-camera-board-1mp-720p-ov9281-uvc-webcam-module-with-low-distortion-m12-lens-without-microphones-for-computer-laptop-android-device-and-raspberry-pi/
[manual]: https://manuals.plus/arducam/b0332-usb-global-shutter-low-distortion-camera-module-manual

Two consequences for the experiments:

- **Focus distance.** The lens is focused at the factory for 1 m to ∞, but the user sits 50–70 cm
  away. Turn the focus ring for that distance before you evaluate image sharpness. Both the
  holder and the mount leave the lens free to turn.
- **Vertical FOV.** Arducam does not state it. The 1280 × 800 mode gives
  2·atan(tan 35° / 1.6) ≈ **47°** for an ideal lens, if the 70° applies to the full sensor width.

## What the mount assumes (measure these)

| Dimension | Assumed | Used for | How to measure |
|---|---|---|---|
| Hole positions | 4 holes at the corners of a 34 × 34 mm square, centred | Standoffs | Calipers, hole edge to hole edge + one diameter. Also check whether a second set exists at 28 × 28 |
| Hole diameter | 2.2 mm (M2 clearance) | Nothing: the holder uses no screws | Calipers or a drill-bit gauge |
| PCB size | 38 × 38 mm | Slide-in slot between the holder walls (0.3 mm play) | Calipers, both directions |
| PCB thickness | 1.6 mm | Slot between the standoffs and the front ribs (0.25 mm play) | Calipers |
| Front-face edge strip | Nothing within 1.2 mm of the left and right edges | The front ribs that hold the board | Look at the front: note any part or pad at the edges |
| Lens axis position | At the PCB centre | Optical centre, baseline | Measure from the barrel edge to two adjacent PCB edges |
| Lens holder footprint and height | 15 × 15 mm, 10 mm | Fit check | Calipers |
| Lens barrel diameter | 14.5 mm | Fit check | Calipers on the focus ring |
| Lens front from PCB face | 22 mm (once focused for 60 cm) | FOV check | Calipers after focusing |
| Optical centre from PCB face | 12 mm | **Position of the yaw and pitch axes** | See below |
| Rear component height | ≤ 3 mm outside a 26 mm central window | Standoff height (5 mm) | Calipers. Note any part taller than 5 mm within 13–19 mm of the centre |
| Connector | 12 × 8 mm, ≤ 7 mm tall, roughly central | Rear window, cable keep-out | Photograph the back next to a ruler. Note the plug direction (straight back or sideways) |

**Optical centre.** The pivots are placed on the lens axis, 12 mm in front of the PCB, so that
yaw and pitch do not move the optical centre and the baseline reads the same at every
angle. The real entrance pupil of an M12 lens is somewhere inside the barrel. To find it,
turn the camera about a vertical axis while it looks at a near and a far object. The pivot
at which they do not shift relative to each other is the entrance pupil. Change
`optical_centre_from_pcb` to the measured value and rebuild.

**Photographs that would help:** front and back of one camera, square-on, next to a ruler,
with the lens focused for 60 cm. Add a side view showing the lens height.
