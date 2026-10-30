# Shared interface: cameras, rig geometry and experiment metadata

**Status: first draft (proposal)** by the camera-diagnostic work, for review by the mount work and
the coordinator. Software and mechanical design must use the same names, frames and units.
The machine-readable form is the experiment config, implemented in
[`software/diagnostic/src/lynx_sight_diag/config.py`](../../software/diagnostic/src/lynx_sight_diag/config.py)
with an example at
[`software/diagnostic/examples/experiment.example.yaml`](../../software/diagnostic/examples/experiment.example.yaml).

## Units

Millimetres and degrees everywhere. Image coordinates are pixels with the origin at the top-left
pixel's top-left corner.

## Cameras

Two identical Arducam B0332 (OV9281, 1280 × 800, monochrome, global shutter, UVC, M12 lens).

| ID | Which one |
|---|---|
| `cam_left` | on the user's left, seen by the user facing the cameras below the monitor |
| `cam_right` | on the user's right |

Because the cameras face the user, `cam_left` appears on the right side of an image taken from
behind the user, and the user's left eye appears in the right half of each camera image. Software
names image features by image position (`eye_image_left`) to avoid this mirror ambiguity.

A camera is bound to its ID by a stable device path, preferably `/dev/v4l/by-path/…` (follows the
USB port), because two identical units may report the same USB serial (`/dev/v4l/by-id/…` then
collides). The serial is recorded too when present. Keep each camera on the same USB port.

## Rig frame

* **Origin:** midpoint between the two cameras' optical centres. Until measured, the optical centre
  is approximated by the M12 lens axis at the PCB centre.
* **Axes (right-handed):** X to the user's right, Y up, Z toward the user.
* **Baseline** `baseline_mm`: distance between the two optical axes at the pivot plane. Nominal 100,
  adjustable about 70–160.

## Camera frame and mounting angles

* Camera frame: OpenCV convention, x right, y down, z forward along the optical axis (toward the
  user when yaw = pitch = 0).
* Per camera, `yaw_deg` and `pitch_deg`: 0 = optical axis parallel to rig Z; positive yaw turns
  the camera toward the rig centre (toe-in), positive pitch tilts it up. Range ±25°.
* These are the mechanical settings read off the mount. They are not calibrated extrinsics; stereo
  calibration will later measure the real pose and supersede them.

## User position

`user_distance_mm`: from the rig origin to the midpoint between the user's eyes, measured along
rig Z. Typical 500–700.

## Experiment config (schema `lynx-sight/experiment/v1`)

| Field | Meaning |
|---|---|
| `experiment_id` | 1–64 characters: letters, digits, `.`, `_`, `-` |
| `notes` | free text |
| `rig.baseline_mm`, `rig.user_distance_mm` | as above |
| `cameras.<id>.device`, `.serial` | stable device path; USB serial if any |
| `cameras.<id>.yaw_deg`, `.pitch_deg` | mechanical angles, ±25° |
| `cameras.<id>.controls` | per-camera V4L2 control overrides |
| `capture.fourcc`, `.width`, `.height`, `.fps` | requested mode (e.g. MJPG 1280×800 @ 60) |
| `capture.controls` | V4L2 controls by normalised name, e.g. `auto_exposure`, `exposure_time_absolute` |
| `processing.<function>` | `enabled`, `max_hz`, `options` |

Every recording stores this config together with what the devices actually negotiated and the
control values read back, so requested and achieved settings are never confused.

## Open points for the mount work

* Measure the optical centre (lens axis and entrance pupil) relative to the PCB mounting holes so
  the origin and baseline can be stated exactly.
* Provide angle scales or detents on the mount so `yaw_deg`/`pitch_deg` can be read reliably and
  recorded per experiment.
* Keep the USB connectors reachable without moving the cameras, so ports (and by-path IDs) stay
  fixed.
