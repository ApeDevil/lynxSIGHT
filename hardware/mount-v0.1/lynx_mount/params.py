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
    """Printed fasteners: one thread for every joint, so the rig needs no bought hardware.

    An 8 mm thread with a 2 mm pitch and 45-degree flanks, not ISO: the flanks print
    without support on screws printed head down and in holes printed vertically, and the
    coarse pitch survives a 0.4 mm nozzle. Screws have the knob as their head.
    """

    major: float = 8.0
    pitch: float = 2.0
    depth: float = 0.75  # 45-degree flanks: flank length along the axis equals the depth
    crest: float = 0.125  # fractions of the pitch; the two flanks share the rest
    root: float = 0.125
    thread_clearance: float = 0.3  # FIT, radial: a threaded hole is the screw grown by this
    shank_clearance: float = 8.8  # FIT: plain hole a screw passes through
    nut_af: float = 13.0
    nut_thickness: float = 6.0
    nut_pocket_af: float = 13.3  # FIT: the nut slides in and cannot turn
    tip_gap: float = 0.5  # a screw stops this short of the end of its thread
    min_engagement: float = 5.0  # 2.5 turns of thread, enough for a hand-tight joint

    @property
    def minor(self) -> float:
        return self.major - 2 * self.depth

    def tap(self) -> dict:
        """Thread arguments of the tap that cuts a threaded hole."""
        return dict(r_major=self.major / 2 + self.thread_clearance, pitch=self.pitch, depth=self.depth,
                    crest=self.crest, root=self.root)

    def rod(self) -> dict:
        return dict(r_major=self.major / 2, pitch=self.pitch, depth=self.depth, crest=self.crest, root=self.root)


@dataclass(frozen=True)
class Print:
    bed_xyz: tuple = (256.0, 256.0, 256.0)  # Bambu Lab P2S build volume (manufacturer spec)
    bed_margin: float = 5.0  # keep parts this far inside each edge
    plate_gap: float = 6.0  # between parts on a ready-arranged plate, room for removal
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
    pcb_side_clearance: float = 0.3  # FIT: the PCB slides down between the side walls
    standoff_height: float = 5.0  # must exceed camera.rear_component_height
    pcb_slot_clearance: float = 0.25  # FIT: PCB between the standoff tops and the front ribs
    front_rib: tuple = (1.2, 1.5)  # (reach over the PCB's side edges, thickness along Z)
    keeper_thickness: float = 2.5  # bar on top of the walls that holds the PCB down
    keeper_peg: tuple = (3.0, 3.2, 5.0)  # peg diameter, hole diameter (FIT), depth
    standoff_diameter: float = 5.5
    rear_plate_thickness: float = 3.0
    rear_window: float = 26.0  # square opening behind the PCB for the connector and parts
    holder_wall: float = 8.5  # holds the printed pitch nut in a pocket on its inner face
    holder_height: float = 42.0  # Y extent of the side walls
    holder_front_radius: float = 10.0  # rounded wall end around the pitch axis
    holder_rear_chamfer: float = 6.0
    pitch_nut_depth: float = 6.2
    index_fin: tuple = (13.0, 18.0, 5.5)  # r_inner, r_outer, protrusion over the arm
    tie_slot: tuple = (3.6, 1.8)  # cable-tie slot (length, width)

    # --- yoke (local frame: yaw axis at x=0, z=0; arm on the outer side, +X for cam_right)
    pivot_above_yoke: float = 33.0  # pitch axis above yoke base top
    yoke_base_thickness: float = 8.0
    yoke_disk_radius: float = 20.0
    arm_thickness: float = 8.0
    arm_width: float = 24.0  # along Z, equal to the boss so the boss needs no overhang
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
    rail_height: float = 24.0
    rail_web: float = 6.0  # top web above the nut tunnel
    slot_width: float = 9.0  # the screw passes with the shank clearance
    tunnel_width: float = 13.4  # > nut AF 13.0, < corners 15.0: the nut slides but cannot spin
    tunnel_height: float = 6.6
    key_channel: tuple = (12.0, 4.0)  # width, height of the groove under the rail that keys the brackets
    rail_axis_z: float = -30.0  # rail centre behind the yaw axes (yaw-axis Z = 0); the yaw knob under
    # the carriage clears the rail's front face, and the lock knobs clear the yoke disk
    scale_strip: float = 6.0  # rail top left visible behind the carriage

    # --- brackets: one under each rail end, either a desk foot or a monitor clamp.
    # Both share the saddle: a block the rail sits on, keyed into the rail's groove and
    # held by one M4 bolt from below into a nut pressed into the groove ceiling.
    bracket_width: float = 30.0  # along X; the bracket ends flush with the rail end
    saddle_thickness: float = 10.0
    saddle_z: tuple = (-50.0, -8.0)  # saddle extent along rig Z (rail spans -44..-16)
    saddle_head_recess: tuple = (16.5, 4.5)  # round recess under the saddle for the screw head (dia, depth)
    bracket_head: tuple = (15.0, 4.0)  # bracket screw head, a knurled disk with a coin slot (dia, height)
    key_clearance: float = 0.2  # per side, saddle boss in the rail groove
    foot_z: tuple = (-95.0, 40.0)  # desk foot pad extent along rig Z
    foot_thickness: float = 5.0

    # --- monitor clamp (rig frame; the monitor's front face is a plane z = monitor_front_z)
    monitor_front_z: float = -12.0  # inner face of the front lip, felt pad included
    felt_thickness: float = 1.5  # self-adhesive felt on every face touching the monitor
    lip_thickness: float = 4.0
    lip_drop: float = 12.0  # how far the lip reaches down over the front bezel
    clamp_bolt_z: float = -20.0  # rear-arm bolt, behind the lip
    clamp_ear: float = 11.0  # block beyond the rail end, up to the rail top, that takes the arm bolt
    clamp_nut_inset: float = 3.0  # skin between the ear's outer face and its drop-in nut slot
    clamp_knob_clearance: float = 2.0  # arm knob above the monitor's top surface
    arm_plate: float = 6.0  # rear arm thickness along X
    arm_bar_height: float = 20.0
    arm_slot: tuple = (6.0, 68.0)  # slot along the bar, measured forward from the leg's inner face
    arm_leg_drop: float = 50.0  # leg length below the monitor top
    arm_bar_front: float = 84.0  # bar length forward of the leg's inner face; carries the depth scale

    # --- knob
    knob_diameter: float = 18.0
    knob_height: float = 8.0
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
    def keeper_z(self) -> float:
        """Centre of the PCB's thickness: where the keeper's tongue and pegs sit."""
        return (self.pcb_front_z + self.pcb_back_z) / 2

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
    def rail_floor_thread(self) -> float:
        """Threaded length from the key groove's ceiling up to the nut tunnel."""
        return self.rail_height - self.rail_web - self.tunnel_height - self.key_channel[1]

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
    """Every printed screw: its thread length, what it grips, how much thread it engages
    and the room left past its tip. A screw's length is its grip plus the engagement it
    needs, less the tip gap, so engagement is the length left inside the nut or hole.
    """
    f = p.fasteners

    def stack(grip, thread, room_past):
        length = grip + thread - f.tip_gap
        return dict(length=round(length, 2), grip=grip, engagement=round(length - grip, 2),
                    tip_room=round(room_past + f.tip_gap, 2))

    return {
        # knob on the carriage -> carriage -> rail web -> nut in the tunnel
        "rail_lock": stack(p.carriage_thickness + p.rail_web, f.nut_thickness, p.tunnel_height - f.nut_thickness),
        # knob under the carriage -> carriage -> thread in the yoke base
        "yaw": stack(p.carriage_thickness, p.yoke_base_thickness, 0.0),
        # knob on the arm -> arm -> gap -> holder wall skin -> nut in the wall's inner pocket;
        # the tip ends inside the holder, beside the lens
        "pitch": stack(p.arm_thickness + p.printing.rotating_gap + (p.holder_wall - p.pitch_nut_depth),
                       f.nut_thickness, p.pitch_nut_depth - f.nut_thickness),
        # head in the saddle's recess -> saddle -> key boss -> thread in the rail floor
        "bracket": stack(p.saddle_thickness - p.saddle_head_recess[1] + p.key_channel[1] - p.key_clearance,
                         p.rail_floor_thread, 0.0),
        # knob on the rear arm -> arm -> ear skin -> nut in the ear's drop-in slot
        "clamp": stack(p.arm_plate + p.clamp_nut_inset, f.nut_thickness,
                       p.clamp_ear - p.clamp_nut_inset - f.nut_thickness - 0.4),
    }


DEFAULT = Mount()
