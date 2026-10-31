//! Display discovery: combines what the window system reports (layout, scaling) with what the
//! kernel reports (connectors, EDID: identity and physical size).
//!
//! Sources on Linux:
//! * **platform monitors**: passed in by the caller (the Tauri shell asks the window system;
//!   works on X11 and Wayland). Positions and sizes are in the window system's pixels, which
//!   is what [`DesktopRect`] holds for this source.
//! * **X11 RandR** (`xrandr --query`): connector names, rotation and layout, when an X server
//!   (or XWayland) answers.
//! * **sysfs** (`/sys/class/drm/card*-*/edid`): connected connectors and their EDID, readable
//!   without a display server.
//!
//! Each source may be missing; what is missing becomes a warning, not an error. A Windows
//! implementation would provide the same facts (EnumDisplayMonitors + the registry EDID) and
//! reuse [`merge`].

use std::path::{Path, PathBuf};
use std::process::Command;

use lynx_sight_contracts::display::{
    DesktopRect, Display, DisplayId, DisplayLayout, PhysicalSize, PixelSize, Rotation,
};
use lynx_sight_contracts::metric::Provenance;

use crate::edid::{self, EdidInfo};

/// A monitor as the window system reports it.
#[derive(Debug, Clone, PartialEq)]
pub struct PlatformMonitor {
    /// Often the model name (GTK) rather than the connector.
    pub name: Option<String>,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub scale_factor: f64,
    pub primary: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Connector {
    /// e.g. `DP-1` (the `cardN-` prefix removed).
    pub name: String,
    pub edid: Option<EdidInfo>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct XrandrOutput {
    pub connector: String,
    pub primary: bool,
    pub desktop: DesktopRect,
    pub rotation: Rotation,
    pub size_mm: Option<(u32, u32)>,
    pub refresh_hz: Option<f64>,
}

/// Everything the sources found, before merging.
#[derive(Debug, Clone, Default)]
pub struct Facts {
    pub platform: Vec<PlatformMonitor>,
    pub xrandr: Vec<XrandrOutput>,
    pub connectors: Vec<Connector>,
    pub sources: Vec<String>,
    pub warnings: Vec<String>,
}

pub trait DisplayDiscovery {
    fn facts(&self, platform: &[PlatformMonitor]) -> Facts;

    fn discover(&self, platform: &[PlatformMonitor]) -> DisplayLayout {
        merge(self.facts(platform))
    }
}

pub struct LinuxDiscovery {
    pub sysfs_drm: PathBuf,
    pub use_xrandr: bool,
}

impl Default for LinuxDiscovery {
    fn default() -> Self {
        LinuxDiscovery {
            sysfs_drm: PathBuf::from("/sys/class/drm"),
            use_xrandr: true,
        }
    }
}

impl DisplayDiscovery for LinuxDiscovery {
    fn facts(&self, platform: &[PlatformMonitor]) -> Facts {
        let mut facts = Facts {
            platform: platform.to_vec(),
            ..Facts::default()
        };
        if !platform.is_empty() {
            facts.sources.push("platform-window-system".into());
        }
        match read_sysfs_connectors(&self.sysfs_drm) {
            Ok((connectors, warnings)) => {
                facts.sources.push("sysfs-edid".into());
                facts.connectors = connectors;
                facts.warnings.extend(warnings);
            }
            Err(e) => facts
                .warnings
                .push(format!("no DRM connectors in sysfs: {e}")),
        }
        if self.use_xrandr {
            match Command::new("xrandr").arg("--query").output() {
                Ok(out) if out.status.success() => {
                    facts.sources.push("x11-randr".into());
                    facts.xrandr = parse_xrandr(&String::from_utf8_lossy(&out.stdout));
                }
                Ok(out) => facts.warnings.push(format!(
                    "xrandr failed (no X server?): {}",
                    String::from_utf8_lossy(&out.stderr).trim()
                )),
                Err(e) => facts.warnings.push(format!("xrandr not available: {e}")),
            }
        }
        facts
    }
}

/// Connected DRM connectors and their EDIDs under `root` (normally `/sys/class/drm`).
pub fn read_sysfs_connectors(root: &Path) -> std::io::Result<(Vec<Connector>, Vec<String>)> {
    let mut connectors = Vec::new();
    let mut warnings = Vec::new();
    let mut entries: Vec<_> = std::fs::read_dir(root)?.flatten().collect();
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        let file_name = entry.file_name().to_string_lossy().to_string();
        let Some((card, name)) = file_name.split_once('-') else {
            continue;
        };
        if !card.starts_with("card") {
            continue;
        }
        let status = std::fs::read_to_string(entry.path().join("status")).unwrap_or_default();
        if status.trim() != "connected" {
            continue;
        }
        let edid = match std::fs::read(entry.path().join("edid")) {
            Ok(bytes) if bytes.is_empty() => None,
            Ok(bytes) => match edid::parse(&bytes) {
                Ok(info) => Some(info),
                Err(e) => {
                    warnings.push(format!("{name}: unusable EDID: {e}"));
                    None
                }
            },
            Err(e) => {
                warnings.push(format!("{name}: EDID not readable: {e}"));
                None
            }
        };
        connectors.push(Connector {
            name: name.to_string(),
            edid,
        });
    }
    Ok((connectors, warnings))
}

/// Parses the connected outputs of `xrandr --query`.
pub fn parse_xrandr(text: &str) -> Vec<XrandrOutput> {
    let mut outputs: Vec<XrandrOutput> = Vec::new();
    for line in text.lines() {
        if !line.starts_with(' ') {
            let words: Vec<&str> = line.split_whitespace().collect();
            if words.len() < 3 || words[1] != "connected" {
                continue;
            }
            let primary = words[2] == "primary";
            let rest = &words[if primary { 3 } else { 2 }..];
            let Some(desktop) = rest.first().and_then(|g| parse_geometry(g)) else {
                continue;
            };
            let rotation = match rest.get(1) {
                Some(&"left") => Rotation::Deg270,
                Some(&"right") => Rotation::Deg90,
                Some(&"inverted") => Rotation::Deg180,
                _ => Rotation::Deg0,
            };
            let size_mm = rest
                .windows(3)
                .find(|w| w[1] == "x" && w[0].ends_with("mm") && w[2].ends_with("mm"))
                .and_then(|w| {
                    let a = w[0].trim_end_matches("mm").parse().ok()?;
                    let b = w[2].trim_end_matches("mm").parse().ok()?;
                    (a > 0 && b > 0).then_some((a, b))
                });
            outputs.push(XrandrOutput {
                connector: words[0].to_string(),
                primary,
                desktop,
                rotation,
                size_mm,
                refresh_hz: None,
            });
        } else if let Some(out) = outputs.last_mut() {
            // Mode lines: "   2560x1440     59.95*+  ..." — `*` marks the current rate.
            if out.refresh_hz.is_none() {
                out.refresh_hz = line
                    .split_whitespace()
                    .skip(1)
                    .find(|w| w.contains('*'))
                    .and_then(|w| w.trim_end_matches(['*', '+']).parse().ok());
            }
        }
    }
    outputs
}

fn parse_geometry(g: &str) -> Option<DesktopRect> {
    // WxH+X+Y; a negative offset is written "+-1920".
    let (size, offsets) = g.split_once('+')?;
    let (w, h) = size.split_once('x')?;
    let (x, y) = offsets.split_once('+')?;
    Some(DesktopRect {
        x: x.parse().ok()?,
        y: y.parse().ok()?,
        width: w.parse().ok()?,
        height: h.parse().ok()?,
    })
}

/// Combines the facts into one display per platform monitor (or per X output, or per
/// connector, whichever source is richest).
pub fn merge(facts: Facts) -> DisplayLayout {
    let mut warnings = facts.warnings.clone();
    let mut displays = Vec::new();
    if !facts.platform.is_empty() {
        for m in &facts.platform {
            let desktop = DesktopRect {
                x: m.x,
                y: m.y,
                width: m.width,
                height: m.height,
            };
            let xr = facts.xrandr.iter().find(|o| o.desktop == desktop);
            let connector = find_connector(
                &facts.connectors,
                xr.map(|o| o.connector.as_str()),
                m.name.as_deref(),
                (m.width, m.height),
            );
            let rotation = match xr {
                Some(o) => o.rotation,
                None => infer_rotation(
                    connector,
                    (m.width, m.height),
                    &mut warnings,
                    &desktop_label(&desktop),
                ),
            };
            displays.push(build(
                connector,
                xr.map(|o| o.connector.clone()),
                m.name.clone(),
                desktop,
                rotation,
                m.scale_factor,
                m.primary || xr.is_some_and(|o| o.primary),
                xr.and_then(|o| o.refresh_hz),
                xr.and_then(|o| o.size_mm),
            ));
        }
    } else if !facts.xrandr.is_empty() {
        for o in &facts.xrandr {
            let connector = find_connector(
                &facts.connectors,
                Some(&o.connector),
                None,
                (o.desktop.width, o.desktop.height),
            );
            displays.push(build(
                connector,
                Some(o.connector.clone()),
                None,
                o.desktop,
                o.rotation,
                1.0,
                o.primary,
                o.refresh_hz,
                o.size_mm,
            ));
        }
    } else {
        // Kernel facts only: the layout is unknown, so lay displays out left to right.
        warnings.push("no window-system layout: display positions are placeholders".into());
        let mut x = 0i32;
        for c in &facts.connectors {
            let mode = c
                .edid
                .as_ref()
                .and_then(|e| e.preferred_mode)
                .unwrap_or(PixelSize {
                    width: 1920,
                    height: 1080,
                });
            let desktop = DesktopRect {
                x,
                y: 0,
                width: mode.width,
                height: mode.height,
            };
            x += mode.width as i32;
            displays.push(build(
                Some(c),
                Some(c.name.clone()),
                None,
                desktop,
                Rotation::Deg0,
                1.0,
                displays.is_empty(),
                None,
                None,
            ));
        }
    }
    if !displays.iter().any(|d| d.primary) {
        if let Some(first) = displays.first_mut() {
            first.primary = true;
        }
    }
    DisplayLayout {
        displays,
        sources: facts.sources,
        warnings,
    }
}

fn desktop_label(r: &DesktopRect) -> String {
    format!("{}x{}+{}+{}", r.width, r.height, r.x, r.y)
}

fn find_connector<'a>(
    connectors: &'a [Connector],
    name: Option<&str>,
    model: Option<&str>,
    visible: (u32, u32),
) -> Option<&'a Connector> {
    if let Some(n) = name {
        if let Some(c) = connectors.iter().find(|c| c.name == n) {
            return Some(c);
        }
    }
    if let Some(model) = model {
        let by_model: Vec<_> = connectors
            .iter()
            .filter(|c| {
                c.edid
                    .as_ref()
                    .and_then(|e| e.name.as_deref())
                    .is_some_and(|n| n.eq_ignore_ascii_case(model))
            })
            .collect();
        if by_model.len() == 1 {
            return Some(by_model[0]);
        }
    }
    let by_mode: Vec<_> = connectors
        .iter()
        .filter(|c| {
            c.edid
                .as_ref()
                .and_then(|e| e.preferred_mode)
                .is_some_and(|m| (m.width, m.height) == visible || (m.height, m.width) == visible)
        })
        .collect();
    (by_mode.len() == 1).then(|| by_mode[0])
}

fn infer_rotation(
    connector: Option<&Connector>,
    visible: (u32, u32),
    warnings: &mut Vec<String>,
    label: &str,
) -> Rotation {
    let native = connector
        .and_then(|c| c.edid.as_ref())
        .and_then(|e| e.preferred_mode);
    match native {
        Some(m) if (m.width > m.height) != (visible.0 > visible.1) && m.width != m.height => {
            warnings.push(format!(
                "{label}: portrait use of a landscape panel; rotation assumed 90°, check it"
            ));
            Rotation::Deg90
        }
        _ => Rotation::Deg0,
    }
}

#[allow(clippy::too_many_arguments)]
fn build(
    connector: Option<&Connector>,
    connector_name: Option<String>,
    platform_name: Option<String>,
    desktop: DesktopRect,
    rotation: Rotation,
    scale_factor: f64,
    primary: bool,
    refresh_hz: Option<f64>,
    xrandr_mm: Option<(u32, u32)>,
) -> Display {
    let edid = connector.and_then(|c| c.edid.as_ref());
    let connector_name = connector_name.or_else(|| connector.map(|c| c.name.clone()));
    // Both sources report the rectangle in device pixels, already rotated.
    let (vw, vh) = (desktop.width, desktop.height);
    let mode = match rotation {
        Rotation::Deg0 | Rotation::Deg180 => PixelSize {
            width: vw,
            height: vh,
        },
        Rotation::Deg90 | Rotation::Deg270 => PixelSize {
            width: vh,
            height: vw,
        },
    };
    // X reports the size already rotated; EDID reports the native panel. Store native.
    let physical = edid.and_then(|e| e.physical).or_else(|| {
        xrandr_mm.map(|(w, h)| {
            let (w, h) = match rotation {
                Rotation::Deg90 | Rotation::Deg270 => (h, w),
                _ => (w, h),
            };
            PhysicalSize {
                width_mm: f64::from(w),
                height_mm: f64::from(h),
                provenance: Provenance::Edid,
            }
        })
    });
    let model = edid
        .and_then(|e| e.name.clone())
        .or(platform_name)
        .unwrap_or_else(|| "display".to_string());
    let name = match &connector_name {
        Some(c) => format!("{model} on {c}"),
        None => model,
    };
    Display {
        id: DisplayId {
            stable: edid.and_then(EdidInfo::stable_id),
            connector: connector_name,
        },
        name,
        desktop,
        mode,
        refresh_hz,
        scale_factor,
        rotation,
        primary,
        physical,
    }
}

/// The user's own measurement replaces the EDID estimate.
pub fn with_measured_size(
    mut display: Display,
    visible_width_mm: f64,
    visible_height_mm: f64,
) -> Display {
    let (w, h) = match display.rotation {
        Rotation::Deg90 | Rotation::Deg270 => (visible_height_mm, visible_width_mm),
        _ => (visible_width_mm, visible_height_mm),
    };
    display.physical = Some(PhysicalSize {
        width_mm: w,
        height_mm: h,
        provenance: Provenance::UserMeasured,
    });
    display
}
