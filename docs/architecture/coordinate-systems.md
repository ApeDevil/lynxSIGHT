# Coordinate systems and units

Every transform between these frames is implemented once, in
[`software/desktop/crates/geometry`](../../software/desktop/crates/geometry/src/lib.rs), and tested
there. The engine (Python) does not transform frames: it works in image coordinates and
normalized display coordinates and receives a precomputed `MetricScale` for physical units.

The exception is the diagnostic's stereo experiment (`lynx_sight_diag.stereo`): it measures the
camera → rig transform by checkerboard calibration, triangulates face landmarks in the rig frame
and intersects gaze rays with a screen plane given in the rig frame, using the same frames and
the same `screen_pose_below_rig` starting estimate. It stays outside the engine protocol until
it is validated on hardware.

Units: millimetres, degrees, pixels; time is CLOCK_MONOTONIC nanoseconds (`*_ns`) or
milliseconds where named `*_ms`.

| Frame | Origin and axes | Unit | Where it is used |
|---|---|---|---|
| **Image** | top-left corner of the top-left pixel; x right, y down | px | features, landmarks (`lynx_sight_diag.processing`) |
| **Camera** | optical centre; OpenCV: x right, y down, z forward along the optical axis | mm | stereo calibration (`lynx_sight_diag.stereo`); `geometry::rig::CameraPose` |
| **Rig** | midpoint of the two optical centres; X to the user's right, Y up, Z toward the user | mm | [shared interface](shared-interface.md); camera mounting, screen pose |
| **Head / eye** | midpoint between the eyes; axes parallel to the rig when the user faces the rig squarely (X to the user's right, Y up, Z out of the back of the head, so gaze is −Z) | mm | defined for future 3-D models; today only uncalibrated pose angles exist |
| **Physical display** | top-left corner of the active area as the user sees it; x right, y down, z into the screen | mm | `MetricScale`, `ScreenPose` |
| **Normalized display** | (0, 0) top-left of the visible image, (1, 1) bottom-right, after rotation | 1 | targets, gaze estimates, pointer intent |
| **Display pixels** | top-left device pixel as seen, after rotation | device px | errors in px |
| **Desktop** | the window system's global space; offsets may be negative | window-system px | pointer intent, monitor selection |

Relations:

* **Camera → rig:** `CameraPose::nominal(side, baseline, yaw, pitch)` from the mount's mechanical
  settings. With yaw = pitch = 0 a camera looks along rig +Z, so image x (right) is rig −X (the
  user's left) and image y (down) is rig −Y. Positive yaw turns toward the rig centre, positive
  pitch tilts up. Nominal only, until stereo calibration measures the extrinsics. The stereo
  calibration defines the rig frame from what it measures: X from cam_left's optical centre to
  cam_right's, Z the mean optical axis made perpendicular to X and turned down by the configured
  pitch, Y = Z × X, origin midway between the optical centres.
* **Physical display → rig:** a `ScreenPose` gives the physical display origin and its x and y
  axes in rig coordinates; z = x × y. For the monitor-top rig, `screen_pose_below_rig(display,
  above_mm, behind_mm)` is the starting estimate (provenance `assumed`) for the user to correct.
* **Normalized ↔ display pixels:** multiply by the visible pixel size (the mode, swapped for 90° and
  270° rotation).
* **Normalized ↔ physical display:** multiply by the visible physical size, if known. Sizes from
  EDID are estimates (`provenance: edid`); a user measurement replaces them
  (`with_measured_size`, `provenance: user_measured`).
* **Normalized ↔ desktop:** the display's desktop rectangle. Under scaled desktops the desktop
  rectangle and the device-pixel mode differ by `scale_factor`.
* **Visual angle:** the engine computes the angle between the eye→target and eye→estimate rays,
  with the eye at `MetricScale.eye_position_mm` (physical display frame). That position is the
  rig-Z point at the viewing distance, so degree errors are only as good as the screen pose and
  distance; without them they are reported as unavailable.

Names of the user's eyes follow the image (`image_left` = smaller x), because the cameras face
the user: the image-left eye is the user's right eye.
