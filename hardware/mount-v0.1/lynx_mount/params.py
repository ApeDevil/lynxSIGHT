"""Every dimension of mount v0.1, in millimetres and degrees.

Rig frame (shared with the diagnostics software):
  origin  midpoint between the two optical centres,
  +X      to the user's right, as seen by the user facing the cameras,
  +Y      up,
  +Z      toward the user (right-handed).
cam_left sits at -X, cam_right at +X. Per camera, yaw_deg and pitch_deg are 0 when the
optical axis is parallel to +Z; positive yaw turns the axis toward the rig centre,
positive pitch turns it up. The yaw and pitch axes both pass through the assumed
optical centre, so the baseline is the same whatever the angles.

Each camera dimension carries its source, because most of them are not yet measured:
  MFR      manufacturer documentation (Arducam B0332 product page / manual)
  ASSUMED  typical for this class of board, not verified — measure before trusting
Mount dimensions are design choices; FIT marks a clearance the fit coupon tests.
"""

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Sourced:
    value: float
    source: str  # "MFR" | "ASSUMED"
    note: str = ""


@dataclass(frozen=True)
class Camera:
    """Arducam B0332 (OV9281, M12) geometry. See docs/hardware/camera-b0332.md."""

    pcb_size: Sourced = Sourced(38.0, "MFR", "38 x 38 mm board")
    pcb_thickness: Sourced = Sourced(1.6, "ASSUMED", "standard FR4")
    hole_pitch_outer: Sourced = Sourced(34.0, "MFR", "'compatible with 34x34' — hole count/positions unconfirmed")
    hole_pitch_inner: Sourced = Sourced(28.0, "MFR", "'compatible with 28x28' — hole count/positions unconfirmed")
    hole_diameter: Sourced = Sourced(2.2, "ASSUMED", "M2 clearance, typical of Arducam 38 mm boards")
    lens_holder_size: Sourced = Sourced(15.0, "ASSUMED", "square M12 holder footprint")
    lens_holder_height: Sourced = Sourced(10.0, "ASSUMED", "PCB front face to holder top")
    lens_barrel_diameter: Sourced = Sourced(14.5, "ASSUMED", "M12x0.5 thread is MFR; outer knurl assumed")
    lens_length_from_pcb: Sourced = Sourced(22.0, "ASSUMED", "PCB front face to lens front")
    optical_centre_from_pcb: Sourced = Sourced(12.0, "ASSUMED", "PCB front face to the pivot point on the lens axis")
    rear_component_height: Sourced = Sourced(3.0, "ASSUMED", "tallest SMD part on the back outside the connector")
    connector_size: tuple = (12.0, 8.0, 7.0)  # ASSUMED keep-out (x, y, depth) for plug body, centred
    hfov_deg: Sourced = Sourced(70.0, "MFR", "horizontal field of view")
    aspect: float = 1280 / 800  # MFR sensor mode

    @property
    def vfov_deg(self) -> float:
        h = math.radians(self.hfov_deg.value) / 2
        return math.degrees(2 * math.atan(math.tan(h) / self.aspect))


@dataclass(frozen=True)
class Fasteners:
    """ISO metric hardware; nominal sizes from DIN 933 / DIN 934 / ISO 4762."""

    m4_clearance: float = 4.5  # FIT
    m4_bolt_length: float = 16.0  # one length for every M4 joint
    m4_head_af: float = 7.0
    m4_head_height: float = 2.8
    m4_nut_af: float = 7.0
    m4_nut_thickness: float = 3.2
    m4_hex_pocket_af: float = 7.3  # FIT: hex head/nut press-in
    m2_clearance: float = 2.4  # FIT
    m2_screw_length: float = 10.0
    m2_nut_af: float = 4.0
    m2_nut_thickness: float = 1.6
    m2_hex_pocket_af: float = 4.25  # FIT
    min_thread_engagement: float = 2.8  # ~0.9 x nut thickness counts as full engagement


@dataclass(frozen=True)
class Print:
    bed_xyz: tuple = (256.0, 256.0, 256.0)  # Bambu Lab P2S build volume (manufacturer spec)
    bed_margin: float = 5.0  # keep parts this far inside each edge
    plate_gap: float = 8.0  # between parts on a ready-arranged plate, room for brims and removal
    sliding_clearance: float = 0.15  # FIT, per side, keys in slots
    rotating_gap: float = 0.5  # holder wall to yoke arm, before the knob is tightened
    max_overhang_deg: float = 45.0
    layer_height: float = 0.2
    engrave_depth: float = 0.6


@dataclass(frozen=True)
class Mount:
    camera: Camera = field(default_factory=Camera)
    fasteners: Fasteners = field(default_factory=Fasteners)
    printing: Print = field(default_factory=Print)

    # --- adjustment targets
    baseline_nominal: float = 100.0
    baseline_min: float = 70.0
    baseline_max: float = 160.0
    yaw_range: float = 25.0
    pitch_range: float = 25.0
    scale_step_deg: float = 5.0
    scale_step_baseline: float = 5.0

    # --- camera holder (local frame: origin at optical centre, axes as the rig at zero angles)
    pcb_side_clearance: float = 1.0
    standoff_height: float = 5.0  # must exceed camera.rear_component_height
    standoff_diameter: float = 5.5
    rear_plate_thickness: float = 3.0
    rear_window: float = 26.0  # square opening behind the PCB for the connector and parts
    holder_wall: float = 6.5
    holder_height: float = 42.0  # Y extent of the side walls
    holder_front_radius: float = 10.0  # rounded wall end around the pitch axis
    holder_rear_chamfer: float = 4.0
    pitch_nut_depth: float = 3.4
    index_fin: tuple = (13.0, 18.0, 5.5)  # r_inner, r_outer, protrusion over the arm
    tie_slot: tuple = (3.6, 1.8)  # cable-tie slot (length, width)

    # --- yoke (local frame: yaw axis at x=0, z=0; arm on the outer side, +X for cam_right)
    pivot_above_yoke: float = 33.0  # pitch axis above yoke base top
    yoke_base_thickness: float = 8.0
    yoke_disk_radius: float = 20.0
    arm_thickness: float = 8.0
    arm_width: float = 24.0  # along Z, equal to the boss so the boss needs no overhang
    yaw_head_pocket_depth: float = 3.0
    yaw_pointer_reach: float = 24.0

    # --- carriage
    carriage_width: float = 56.0  # along X
    carriage_thickness: float = 6.0
    carriage_front: float = 30.0  # Z of its front edge, in yaw-axis coordinates
    lock_bolt_offset: float = 14.0  # rail-lock bolts at x = ±offset
    key_height: float = 2.0
    yaw_tick_radii: tuple = (24.5, 28.5)

    # --- rail
    rail_length: float = 216.0
    rail_depth: float = 28.0  # along Z
    rail_height: float = 22.0
    rail_web: float = 6.0  # top web above the nut tunnel
    slot_width: float = 4.4
    tunnel_width: float = 7.4  # > nut AF 7.0, < corners 8.08: the nut slides but cannot spin
    tunnel_height: float = 4.5
    key_channel: tuple = (12.0, 4.0)  # width, height of the groove under the rail that keys the brackets
    rail_axis_z: float = -40.0  # rail centre behind the yaw axes (yaw-axis Z = 0)
    scale_strip: float = 6.0  # rail top left visible behind the carriage

    # --- brackets: one under each rail end, either a desk foot or a monitor clamp.
    # Both share the saddle: a block the rail sits on, keyed into the rail's groove and
    # held by one M4 bolt from below into a nut pressed into the groove ceiling.
    bracket_width: float = 40.0  # along X; the bracket ends flush with the rail end
    saddle_thickness: float = 10.0
    saddle_z: tuple = (-60.0, -18.0)  # saddle extent along rig Z (rail spans -54..-26)
    saddle_head_pocket: float = 3.0
    rail_nut_pocket: float = 3.4
    bracket_blind_hole: float = 3.0  # bolt hole continuing above the rail nut pocket
    key_clearance: float = 0.2  # per side, saddle boss in the rail groove
    foot_z: tuple = (-95.0, 40.0)  # desk foot pad extent along rig Z
    foot_thickness: float = 5.0

    # --- monitor clamp (rig frame; the monitor's front face is a plane z = monitor_front_z)
    monitor_front_z: float = -22.0  # inner face of the front lip, felt pad included
    felt_thickness: float = 1.5  # self-adhesive felt on every face touching the monitor
    lip_thickness: float = 4.0
    lip_drop: float = 12.0  # how far the lip reaches down over the front bezel
    clamp_bolt_z: float = -30.0  # rear-arm bolt, behind the lip
    clamp_ear: float = 11.0  # block beyond the rail end, up to the rail top, that takes the arm bolt
    clamp_nut_inset: float = 3.0  # skin between the ear's outer face and its drop-in nut slot
    clamp_knob_clearance: float = 2.0  # arm knob above the monitor's top surface
    arm_plate: float = 6.0  # rear arm thickness along X
    arm_bar_height: float = 22.0
    arm_slot: tuple = (6.0, 68.0)  # slot along the bar, measured forward from the leg's inner face
    arm_leg_drop: float = 50.0  # leg length below the monitor top
    arm_bar_front: float = 84.0  # bar length forward of the leg's inner face; carries the depth scale

    # --- knob
    knob_diameter: float = 22.0
    knob_height: float = 9.0
    knob_pocket_depth: float = 2.6  # < head and nut, so the steel bears, not the knob
    knob_lobes: int = 8

    # --- where the user's eyes are expected (for the field-of-view check, not the geometry)
    user_distance: tuple = (500.0, 700.0)  # eyes to the screen
    eye_above_monitor_top: tuple = (-150.0, 50.0)  # ergonomic setups put the top edge near eye level

    # ------------------------------------------------------------ derived geometry
    @property
    def pcb_half(self) -> float:
        return self.camera.pcb_size.value / 2

    @property
    def pcb_front_z(self) -> float:
        return -self.camera.optical_centre_from_pcb.value

    @property
    def pcb_back_z(self) -> float:
        return self.pcb_front_z - self.camera.pcb_thickness.value

    @property
    def rear_plate_front_z(self) -> float:
        return self.pcb_back_z - self.standoff_height

    @property
    def rear_plate_back_z(self) -> float:
        return self.rear_plate_front_z - self.rear_plate_thickness

    @property
    def wall_inner_x(self) -> float:
        return self.pcb_half + self.pcb_side_clearance

    @property
    def wall_outer_x(self) -> float:
        return self.wall_inner_x + self.holder_wall

    @property
    def arm_inner_x(self) -> float:
        return self.wall_outer_x + self.printing.rotating_gap

    @property
    def arm_outer_x(self) -> float:
        return self.arm_inner_x + self.arm_thickness

    @property
    def yoke_top_y(self) -> float:
        return -self.pivot_above_yoke

    @property
    def yoke_bottom_y(self) -> float:
        return self.yoke_top_y - self.yoke_base_thickness

    @property
    def rail_top_y(self) -> float:
        return self.yoke_bottom_y - self.carriage_thickness

    @property
    def rail_bottom_y(self) -> float:
        return self.rail_top_y - self.rail_height

    @property
    def surface_y(self) -> float:
        """Top of whatever the brackets stand on: the desk, or the monitor's top edge."""
        return self.rail_bottom_y - self.saddle_thickness

    @property
    def bracket_centre_x(self) -> float:
        return self.rail_length / 2 - self.bracket_width / 2

    @property
    def clamp_bolt_y(self) -> float:
        """High enough that the arm's knob clears the top of the monitor."""
        return self.surface_y - self.felt_thickness + self.knob_diameter / 2 + self.clamp_knob_clearance

    @property
    def monitor_depth_range(self) -> tuple:
        """Monitor depths (front face to back, where the arm's leg touches) the clamp grips."""
        s0, s1 = self.arm_slot
        # leg inner face = bolt - slot position; the felt on the leg sits in between
        base = self.monitor_front_z - self.felt_thickness - self.clamp_bolt_z
        return (base + s0, base + s1)

    @property
    def carriage_back_z(self) -> float:
        return self.rail_axis_z - self.rail_depth / 2 + self.scale_strip

    def baseline_ticks(self):
        """(baseline, carriage-centre |x|) pairs engraved on the rail."""
        n = int(round((self.baseline_max - self.baseline_min) / self.scale_step_baseline))
        return [(self.baseline_min + i * self.scale_step_baseline,
                 (self.baseline_min + i * self.scale_step_baseline) / 2) for i in range(n + 1)]

    def angle_ticks(self, limit: float):
        n = int(round(limit / self.scale_step_deg))
        return [i * self.scale_step_deg for i in range(-n, n + 1)]


def fastener_stacks(p: Mount) -> dict:
    """Thread engagement and tip room of every M4 joint, from the part dimensions.

    grip: material clamped between head and nut; engagement: bolt length inside the nut;
    tip_room: free space left past the bolt tip before it meets another part.
    """
    f = p.fasteners
    L = f.m4_bolt_length

    def stack(grip, room_past_nut):
        past_nut = L - grip - f.m4_nut_thickness
        return dict(grip=grip, engagement=min(L - grip, f.m4_nut_thickness),
                    tip_room=room_past_nut - max(0.0, past_nut))

    knob_sink = f.m4_nut_thickness - p.knob_pocket_depth  # nut/head standing proud of the knob
    return {
        # head under a knob on the carriage -> carriage -> rail web -> nut held in the tunnel
        "rail_lock": stack(p.carriage_thickness + p.rail_web,
                           p.tunnel_height - f.m4_nut_thickness),
        # head in the yoke pocket -> yoke -> carriage -> nut in a knob below the carriage;
        # the tip leaves through the knob's bore, so the room is the knob's clearance over the foot
        "yaw": stack((p.yoke_base_thickness - p.yaw_head_pocket_depth) + p.carriage_thickness,
                     (p.rail_top_y - p.surface_y - p.foot_thickness) - (p.knob_height + knob_sink)),
        # head under a knob on the arm -> arm -> gap -> holder wall skin -> nut pocket; the tip
        # enters the holder in front of the PCB, beside the lens
        "pitch": stack(p.arm_thickness + p.printing.rotating_gap + (p.holder_wall - p.pitch_nut_depth),
                       p.pitch_nut_depth - f.m4_nut_thickness
                       + p.wall_inner_x - p.camera.lens_barrel_diameter.value / 2),
        # head in a pocket under the saddle -> saddle -> key boss -> nut in the groove
        # ceiling; the tip runs on into a blind hole above the nut pocket
        "bracket_to_rail": stack((p.saddle_thickness - p.saddle_head_pocket) + p.key_channel[1] - p.key_clearance,
                                 p.rail_nut_pocket - f.m4_nut_thickness + p.bracket_blind_hole),
        # head under a knob on the rear arm -> arm -> saddle skin -> nut in a drop-in slot;
        # the tip runs on in the bolt hole across the saddle
        "clamp_arm": stack(p.arm_plate + p.clamp_nut_inset,
                           p.clamp_ear - p.clamp_nut_inset - f.m4_nut_thickness),
    }


DEFAULT = Mount()
