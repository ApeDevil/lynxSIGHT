//! Displays, the desktop layout and the physical display geometry.
//!
//! Frames (see `docs/architecture/coordinate-systems.md`):
//! * **desktop**: the OS's global coordinate space, in desktop units (logical pixels under
//!   Wayland and scaled X11 desktops), y down, origin at the OS's choice: other displays may
//!   have negative offsets.
//! * **display pixels**: device pixels of one display as the user sees it, after rotation.
//! * **normalized display**: display pixels divided by the display's size in pixels.
//! * **physical display**: millimetres on the active area, origin top-left as seen, x right,
//!   y down, z into the screen.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use ts_rs::TS;

use crate::metric::Provenance;

/// Panel rotation applied by the OS, clockwise as seen by the user.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema, TS)]
#[serde(rename_all = "snake_case")]
#[ts(export)]
pub enum Rotation {
    #[default]
    Deg0,
    Deg90,
    Deg180,
    Deg270,
}

/// How a display is recognised again later.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct DisplayId {
    /// Stable across reboots and ports when the EDID carries a serial:
    /// `edid:<manufacturer>-<product code hex>-<serial>`. None when no EDID was found.
    pub stable: Option<String>,
    /// The connector it is attached to (`DP-1`, `HDMI-A-1`, `eDP-1`), if known. Changes with
    /// the cable.
    pub connector: Option<String>,
}

/// A rectangle in desktop units.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct DesktopRect {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

/// A size in device pixels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct PixelSize {
    pub width: u32,
    pub height: u32,
}

/// The active area's physical size, of the panel in its native (unrotated) orientation.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct PhysicalSize {
    pub width_mm: f64,
    pub height_mm: f64,
    pub provenance: Provenance,
}

/// One display as the OS presents it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct Display {
    pub id: DisplayId,
    /// Human-readable label, e.g. `DEL U2720Q on DP-1`.
    pub name: String,
    /// Where the display sits in the desktop, in desktop units.
    pub desktop: DesktopRect,
    /// The current mode in device pixels, of the panel in its native orientation.
    pub mode: PixelSize,
    pub refresh_hz: Option<f64>,
    /// Device pixels per desktop unit (1.0, 1.25, 2.0, ...).
    pub scale_factor: f64,
    pub rotation: Rotation,
    pub primary: bool,
    /// None when neither EDID nor the user supplied a size.
    pub physical: Option<PhysicalSize>,
}

/// All displays found, and which discovery sources contributed.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct DisplayLayout {
    pub displays: Vec<Display>,
    /// e.g. `["platform-window-system", "sysfs-edid"]`.
    pub sources: Vec<String>,
    /// Discovery problems that did not stop discovery (no EDID access, no X server, ...).
    pub warnings: Vec<String>,
}

/// Where the physical display sits relative to the camera rig (rig frame, millimetres; see
/// `docs/architecture/shared-interface.md`).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct ScreenPose {
    /// The physical display's origin (top-left of the active area as seen) in the rig frame.
    pub origin_mm: [f64; 3],
    /// Unit vector of the physical display's x axis (to the right on screen) in the rig frame.
    pub x_axis: [f64; 3],
    /// Unit vector of the physical display's y axis (down on screen) in the rig frame.
    pub y_axis: [f64; 3],
    pub provenance: Provenance,
}

/// What the profile knows about the display it was calibrated on.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema, TS)]
#[ts(export)]
pub struct DisplayCalibration {
    pub display: Display,
    /// None until measured or calibrated: then millimetre and degree errors are unavailable.
    pub screen_pose: Option<ScreenPose>,
    /// Typical distance of the user's eyes from the rig origin along rig Z.
    pub viewing_distance_mm: Option<f64>,
    pub viewing_distance_provenance: Option<Provenance>,
}
