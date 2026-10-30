"""Where each part sits in the rig frame for a given baseline and per-camera yaw/pitch.

A pose maps instance names to 4x4 matrices from the part's local frame (see parts.py)
into the rig frame. Blender's world is Z-up, so the scene root applies RIG_TO_BLENDER
once: rig (x, y, z) -> Blender (x, -z, y), i.e. +90 degrees about X.
"""

from dataclasses import dataclass
import math

from mathutils import Matrix

from .params import Mount

RIG_TO_BLENDER = Matrix.Rotation(math.radians(90), 4, "X")
SIDES = {"left": -1, "right": 1}


@dataclass(frozen=True)
class Setting:
    """Adjustment of one camera, in the shared conventions."""

    yaw_deg: float = 0.0
    pitch_deg: float = 0.0


STANDS = ("monitor", "desk")


@dataclass(frozen=True)
class Pose:
    baseline: float
    left: Setting = Setting()
    right: Setting = Setting()
    stand: str = "monitor"  # monitor clamps on the top edge, or desk feet
    monitor_depth: float = 30.0  # front face to back, where the clamp's rear arm touches

    def setting(self, side):
        return self.left if side == "left" else self.right


def _rx(deg):
    return Matrix.Rotation(math.radians(deg), 4, "X")


def _ry(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Y")


def _t(x, y, z):
    return Matrix.Translation((x, y, z))


def yaw_rotation(side, yaw_deg):
    """Positive yaw turns the optical axis (+Z) toward the rig centre."""
    return _ry(-SIDES[side] * yaw_deg)


def pitch_rotation(pitch_deg):
    """Positive pitch turns the optical axis (+Z) up (+Y)."""
    return _rx(-pitch_deg)


def camera_frames(p: Mount, pose: Pose, side):
    """(carriage frame, yoke frame, holder frame) of one camera in the rig frame."""
    s = pose.setting(side)
    carriage = _t(SIDES[side] * pose.baseline / 2, 0.0, 0.0)
    yoke = carriage @ yaw_rotation(side, s.yaw_deg)
    holder = yoke @ pitch_rotation(s.pitch_deg)
    return carriage, yoke, holder


def _rz(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Z")


SEAT = 0.05  # a screw head or nut stands this far off its bearing face, so contact is not overlap


def fastener_mounts(p: Mount, side):
    """Printed screws, nuts and the PCB keeper of one camera stack:
    (instance suffix, part key, frame it rides on, local matrix)."""
    f = p.fasteners
    sx = SIDES[side]
    zr = p.rail_axis_z
    nut_low = p.rail_top_y - p.rail_web - SEAT - f.nut_thickness
    out = []
    for i, x in enumerate((-p.lock_bolt_offset, p.lock_bolt_offset)):
        # head on the carriage top, shank down; the nut in the tunnel, corners along the rail
        out.append((f"rail_lock_{i + 1}", "screw_rail_lock", "carriage",
                    _t(x, p.yoke_bottom_y + SEAT, zr) @ _rx(90)))
        out.append((f"rail_lock_{i + 1}", "nut", "carriage", _t(x, nut_low, zr) @ _rx(-90) @ _rz(90)))
    # head under the carriage, threaded into the yoke base
    out.append(("yaw", "screw_yaw", "carriage", _t(0.0, p.rail_top_y - SEAT, 0.0) @ _rx(-90)))
    # head outside the arm; the nut in the holder wall's inner pocket
    out.append(("pitch", "screw_pitch", "yoke", _t(sx * (p.arm_outer_x + SEAT), 0.0, 0.0) @ _ry(-sx * 90)))
    out.append(("pitch", "nut", "holder", _t(sx * (p.wall_inner_x + 0.1), 0.0, 0.0) @ _ry(sx * 90)))
    out.append(("", "pcb_keeper", "holder", Matrix.Identity(4)))
    return out


def instance_matrices(p: Mount, pose: Pose):
    """{instance name: (part key, rig matrix, moving group)} for the whole rig.

    The moving group says what an instance turns with: 'static', '<side>.yoke' or
    '<side>.holder'.
    """
    out = {"rail": ("rail", Matrix.Identity(4), "static")}
    out.update(stand_matrices(p, pose))
    for side in SIDES:
        carriage, yoke, holder = camera_frames(p, pose, side)
        out[f"carriage_{side}"] = (f"carriage_{side}", carriage, f"{side}.carriage")
        out[f"yoke_{side}"] = (f"yoke_{side}", yoke, f"{side}.yoke")
        out[f"camera_holder_{side}"] = ("camera_holder", holder, f"{side}.holder")
        frames = {"carriage": carriage, "yoke": yoke, "holder": holder}
        for suffix, key, rides, local in fastener_mounts(p, side):
            kind = "screw" if key.startswith("screw") else key
            out[f"{kind}_{side}" + (f"_{suffix}" if suffix else "")] = (key, frames[rides] @ local, f"{side}.{rides}")
    return out


def stand_matrices(p: Mount, pose: Pose):
    """The brackets under the rail ends with their screws, and for the monitor stand the
    rear arms with their screws and nuts."""
    f = p.fasteners
    out = {}
    L = p.rail_length / 2
    w = p.bracket_width / 2
    for side, sx in SIDES.items():
        bx = sx * p.bracket_centre_x
        centre = _t(bx, 0.0, 0.0)
        # Head in the saddle's recess, threaded up into the rail floor.
        out[f"screw_{side}_bracket"] = ("screw_bracket", _t(bx, p.surface_y + p.saddle_head_recess[1] - SEAT,
                                                            p.rail_axis_z) @ _rx(-90), "static")
        if pose.stand == "desk":
            out[f"desk_foot_{side}"] = ("desk_foot", centre, "static")
            continue
        out[f"monitor_clamp_{side}"] = (f"monitor_clamp_{side}", centre, "static")
        # The arm sits on the ear's outer face; its leg's felt touches the monitor back.
        leg_z = p.monitor_front_z - pose.monitor_depth - p.felt_thickness
        outer = L + p.clamp_ear
        x0 = outer if sx > 0 else -outer - p.arm_plate
        out[f"clamp_arm_{side}"] = ("clamp_arm", _t(x0, 0.0, leg_z), "static")
        out[f"screw_{side}_clamp"] = ("screw_clamp", _t(sx * (outer + p.arm_plate + SEAT), p.clamp_bolt_y,
                                                        p.clamp_bolt_z) @ _ry(-sx * 90), "static")
        nut_x = bx + sx * (w + p.clamp_ear - p.clamp_nut_inset - SEAT)
        out[f"nut_{side}_clamp"] = ("nut", _t(nut_x, p.clamp_bolt_y, p.clamp_bolt_z) @ _ry(-sx * 90), "static")
    return out


def monitor_matrix(p: Mount, pose: Pose):
    """Frame of the monitor reference volume: its front-top edge at the origin."""
    return _t(0.0, p.surface_y - p.felt_thickness, p.monitor_front_z)


def camera_matrices(p: Mount, pose: Pose):
    return {side: camera_frames(p, pose, side)[2] for side in SIDES}


# Exploded view: lift each layer of the stack along its own assembly direction.
EXPLODE = {
    "carriage": Matrix.Translation((0, 18, 0)),
    "yoke": Matrix.Translation((0, 40, 0)),
    "holder": Matrix.Translation((0, 62, 22)),
    "camera": Matrix.Translation((0, 62, 55)),
}
