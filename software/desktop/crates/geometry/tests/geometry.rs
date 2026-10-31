use lynx_sight_contracts::display::*;
use lynx_sight_contracts::metric::{NormPoint, Provenance};
use lynx_sight_contracts::pointer::DesktopPoint;
use lynx_sight_geometry::discovery::*;
use lynx_sight_geometry::rig::{CameraPose, CameraSide};
use lynx_sight_geometry::*;

fn display(x: i32, y: i32, w: u32, h: u32, scale: f64, rotation: Rotation) -> Display {
    let mode = match rotation {
        Rotation::Deg90 | Rotation::Deg270 => PixelSize {
            width: h,
            height: w,
        },
        _ => PixelSize {
            width: w,
            height: h,
        },
    };
    Display {
        id: DisplayId {
            stable: None,
            connector: None,
        },
        name: "test".into(),
        desktop: DesktopRect {
            x,
            y,
            width: w,
            height: h,
        },
        mode,
        refresh_hz: Some(60.0),
        scale_factor: scale,
        rotation,
        primary: false,
        physical: Some(PhysicalSize {
            width_mm: 597.0,
            height_mm: 336.0,
            provenance: Provenance::Edid,
        }),
    }
}

fn close(a: f64, b: f64) -> bool {
    (a - b).abs() < 1e-9
}

#[test]
fn desktop_round_trip_with_negative_offsets_and_mixed_scaling() {
    let left = display(-1920, 120, 1920, 1080, 1.0, Rotation::Deg0);
    let right = display(0, 0, 2560, 1440, 1.5, Rotation::Deg0);
    let layout = DisplayLayout {
        displays: vec![left.clone(), right.clone()],
        sources: vec![],
        warnings: vec![],
    };
    let p = NormPoint { x: 0.25, y: 0.5 };
    let d = norm_to_desktop(&left, p);
    assert!(close(d.x, -1440.0) && close(d.y, 660.0));
    let (found, n) = display_at(&layout, d).unwrap();
    assert_eq!(found.desktop, left.desktop);
    assert!(close(n.x, 0.25) && close(n.y, 0.5));
    let (found, _) = display_at(&layout, DesktopPoint { x: 10.0, y: 10.0 }).unwrap();
    assert_eq!(found.desktop, right.desktop);
    assert!(
        display_at(&layout, DesktopPoint { x: -10.0, y: 50.0 }).is_none(),
        "gap above the left display"
    );
}

#[test]
fn rotation_swaps_visible_pixel_and_physical_sizes() {
    let portrait = display(0, 0, 1080, 1920, 1.0, Rotation::Deg90);
    assert_eq!(visible_px(&portrait), (1080, 1920));
    assert_eq!(
        portrait.mode,
        PixelSize {
            width: 1920,
            height: 1080
        }
    );
    let (w, h) = visible_mm(&portrait).unwrap();
    assert!(close(w, 336.0) && close(h, 597.0));
    let (x, y) = norm_to_physical_mm(&portrait, NormPoint { x: 1.0, y: 0.5 }).unwrap();
    assert!(close(x, 336.0) && close(y, 298.5));
    let back = display_px_to_norm(&portrait, 540.0, 1920.0);
    assert!(close(back.x, 0.5) && close(back.y, 1.0));
}

#[test]
fn physical_rig_transforms_invert_each_other() {
    let d = display(0, 0, 2560, 1440, 1.0, Rotation::Deg0);
    let pose = screen_pose_below_rig(&d, 30.0, 15.0).unwrap();
    // The screen centre lies centred below the rig, behind it.
    let c = physical_to_rig(&pose, [298.5, 168.0, 0.0]);
    assert!(close(c[0], 0.0) && close(c[1], -198.0) && close(c[2], -15.0));
    let p = [12.0, -40.0, 300.0];
    let back = physical_to_rig(&pose, rig_to_physical(&pose, p));
    assert!(p.iter().zip(back).all(|(a, b)| close(*a, b)));
}

#[test]
fn metric_scale_needs_pose_and_distance_for_the_eye_position() {
    let d = display(0, 0, 2560, 1440, 1.0, Rotation::Deg0);
    let mut cal = DisplayCalibration {
        display: d.clone(),
        screen_pose: None,
        viewing_distance_mm: Some(600.0),
        viewing_distance_provenance: Some(Provenance::Assumed),
    };
    let s = metric_scale(&cal);
    assert_eq!((s.width_px, s.height_px), (2560, 1440));
    assert_eq!(s.width_mm, Some(597.0));
    assert_eq!(s.eye_position_mm, None);
    cal.screen_pose = screen_pose_below_rig(&d, 30.0, 15.0);
    let eye = metric_scale(&cal).eye_position_mm.unwrap();
    // Centred, 30 mm above the top edge, 615 mm in front of the screen plane.
    assert!(close(eye[0], 298.5) && close(eye[1], -30.0) && close(eye[2], -615.0));
    cal.display.physical = None;
    let s = metric_scale(&cal);
    assert_eq!((s.width_mm, s.eye_position_mm), (None, None));
}

#[test]
fn nominal_camera_poses_follow_the_shared_interface() {
    let left = CameraPose::nominal(CameraSide::Left, 257.0, 0.0, 0.0);
    assert_eq!(left.position_mm, [-128.5, 0.0, 0.0]);
    // Looking at the user: camera z is rig +Z, image right is the user's left (-X).
    let ahead = left.camera_to_rig([0.0, 0.0, 600.0]);
    assert!(close(ahead[0], -128.5) && close(ahead[2], 600.0));
    let right_in_image = left.camera_to_rig([10.0, 0.0, 0.0]);
    assert!(close(right_in_image[0], -138.5));
    // Toe-in of the left camera turns its axis toward +X; pitch up raises it.
    let toed = CameraPose::nominal(CameraSide::Left, 257.0, 10.0, 5.0);
    let axis = toed.axes[2];
    assert!(axis[0] > 0.0 && axis[1] > 0.0);
    let toed_right = CameraPose::nominal(CameraSide::Right, 257.0, 10.0, 0.0);
    assert!(toed_right.axes[2][0] < 0.0);
    let p = [5.0, -3.0, 500.0];
    let back = toed.rig_to_camera(toed.camera_to_rig(p));
    assert!(p.iter().zip(back).all(|(a, b)| (a - b).abs() < 1e-9));
}

#[test]
fn edid_round_trip_gives_identity_size_and_mode() {
    let bytes = lynx_sight_geometry::edid::synthesize(
        "DEL",
        0x41a2,
        12345,
        "DELL U2720Q",
        (3840, 2160),
        (597, 336),
    );
    let info = lynx_sight_geometry::edid::parse(&bytes).unwrap();
    assert_eq!(info.manufacturer, "DEL");
    assert_eq!(info.name.as_deref(), Some("DELL U2720Q"));
    assert_eq!(
        info.preferred_mode,
        Some(PixelSize {
            width: 3840,
            height: 2160
        })
    );
    let p = info.physical.unwrap();
    assert_eq!(
        (p.width_mm, p.height_mm, p.provenance),
        (597.0, 336.0, Provenance::Edid)
    );
    assert_eq!(info.stable_id().as_deref(), Some("edid:DEL-41a2-12345"));
    let mut broken = bytes.clone();
    broken[30] ^= 1;
    assert!(lynx_sight_geometry::edid::parse(&broken).is_err());
    assert!(lynx_sight_geometry::edid::parse(&bytes[..100]).is_err());
}

#[test]
fn edid_without_serial_has_no_stable_id() {
    let bytes =
        lynx_sight_geometry::edid::synthesize("AUO", 1, 0, "panel", (1920, 1080), (344, 194));
    assert_eq!(
        lynx_sight_geometry::edid::parse(&bytes)
            .unwrap()
            .stable_id(),
        None
    );
}

const XRANDR: &str = "Screen 0: minimum 320 x 200, current 4480 x 1440, maximum 16384 x 16384
DP-1 connected primary 2560x1440+1920+0 (normal left inverted right x axis y axis) 597mm x 336mm
   2560x1440     59.95*+  74.97
   1920x1080     60.00
HDMI-A-1 connected 1080x1920+0+0 right (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+
DP-2 disconnected (normal left inverted right x axis y axis)
";

#[test]
fn xrandr_output_is_parsed() {
    let outputs = parse_xrandr(XRANDR);
    assert_eq!(outputs.len(), 2);
    assert_eq!(outputs[0].connector, "DP-1");
    assert!(outputs[0].primary);
    assert_eq!(
        outputs[0].desktop,
        DesktopRect {
            x: 1920,
            y: 0,
            width: 2560,
            height: 1440
        }
    );
    assert_eq!(outputs[0].size_mm, Some((597, 336)));
    assert_eq!(outputs[0].refresh_hz, Some(59.95));
    assert_eq!(outputs[1].rotation, Rotation::Deg90);
}

#[test]
fn sysfs_connectors_are_read_and_bad_edids_reported() {
    let dir = tempfile::tempdir().unwrap();
    let add = |name: &str, status: &str, edid: &[u8]| {
        let p = dir.path().join(name);
        std::fs::create_dir(&p).unwrap();
        std::fs::write(p.join("status"), status).unwrap();
        std::fs::write(p.join("edid"), edid).unwrap();
    };
    add(
        "card1-DP-1",
        "connected\n",
        &lynx_sight_geometry::edid::synthesize("DEL", 2, 7, "A", (2560, 1440), (597, 336)),
    );
    add("card1-HDMI-A-1", "connected\n", &[1, 2, 3]);
    add("card1-DP-2", "disconnected\n", &[]);
    std::fs::create_dir(dir.path().join("version")).unwrap();
    let (connectors, warnings) = read_sysfs_connectors(dir.path()).unwrap();
    assert_eq!(
        connectors
            .iter()
            .map(|c| c.name.as_str())
            .collect::<Vec<_>>(),
        ["DP-1", "HDMI-A-1"]
    );
    assert!(connectors[0].edid.is_some() && connectors[1].edid.is_none());
    assert_eq!(warnings.len(), 1);
}

#[test]
fn merge_matches_platform_monitors_to_connectors() {
    let edid = |name, serial, mode, mm| {
        lynx_sight_geometry::edid::parse(&lynx_sight_geometry::edid::synthesize(
            "DEL", 2, serial, name, mode, mm,
        ))
        .ok()
    };
    let facts = Facts {
        platform: vec![
            PlatformMonitor {
                name: Some("U2720Q".into()),
                x: 1920,
                y: 0,
                width: 2560,
                height: 1440,
                scale_factor: 1.5,
                primary: true,
            },
            PlatformMonitor {
                name: Some("Side".into()),
                x: 0,
                y: 0,
                width: 1080,
                height: 1920,
                scale_factor: 1.0,
                primary: false,
            },
        ],
        xrandr: parse_xrandr(XRANDR),
        connectors: vec![
            Connector {
                name: "DP-1".into(),
                edid: edid("U2720Q", 9, (2560, 1440), (597, 336)),
            },
            Connector {
                name: "HDMI-A-1".into(),
                edid: edid("Side", 0, (1920, 1080), (527, 296)),
            },
        ],
        sources: vec!["test".into()],
        warnings: vec![],
    };
    let layout = merge(facts);
    let [main, side] = &layout.displays[..] else {
        panic!()
    };
    assert_eq!(main.id.connector.as_deref(), Some("DP-1"));
    assert_eq!(main.id.stable.as_deref(), Some("edid:DEL-0002-9"));
    assert_eq!(main.scale_factor, 1.5);
    assert!(main.primary && !side.primary);
    assert_eq!(side.rotation, Rotation::Deg90);
    assert_eq!(
        side.mode,
        PixelSize {
            width: 1920,
            height: 1080
        }
    );
    assert_eq!(visible_mm(side).map(|m| m.0), Some(296.0));
}

#[test]
fn merge_without_xrandr_infers_portrait_rotation_and_warns() {
    let facts = Facts {
        platform: vec![PlatformMonitor {
            name: Some("Side".into()),
            x: -1080,
            y: 0,
            width: 1080,
            height: 1920,
            scale_factor: 1.0,
            primary: false,
        }],
        connectors: vec![Connector {
            name: "HDMI-A-1".into(),
            edid: lynx_sight_geometry::edid::parse(&lynx_sight_geometry::edid::synthesize(
                "ACR",
                2,
                0,
                "Side",
                (1920, 1080),
                (527, 296),
            ))
            .ok(),
        }],
        ..Facts::default()
    };
    let layout = merge(facts);
    assert_eq!(layout.displays[0].rotation, Rotation::Deg90);
    assert!(
        layout.displays[0].primary,
        "the only display becomes primary"
    );
    assert_eq!(layout.warnings.len(), 1);
}

#[test]
fn merge_with_nothing_found_is_empty_not_an_error() {
    let layout = merge(Facts {
        warnings: vec!["no sysfs".into()],
        ..Facts::default()
    });
    assert!(layout.displays.is_empty());
    assert_eq!(layout.warnings.len(), 2);
}

#[test]
fn user_measurement_replaces_the_edid_size() {
    let d = with_measured_size(
        display(0, 0, 1080, 1920, 1.0, Rotation::Deg90),
        335.0,
        596.0,
    );
    let p = d.physical.unwrap();
    assert_eq!(
        (p.width_mm, p.height_mm, p.provenance),
        (596.0, 335.0, Provenance::UserMeasured)
    );
}
