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


def knob_mounts(p: Mount, side):
    """Knob placements: (instance suffix, frame it rides on, local matrix).

    Each knob's pocket face sits proud of its part by the head/nut height minus the pocket
    depth, because the steel bears on the part, not the knob.
    """
    f = p.fasteners
    head_proud = f.m4_head_height - p.knob_pocket_depth
    nut_proud = f.m4_nut_thickness - p.knob_pocket_depth
    h = p.knob_height
    sx = SIDES[side]
    mounts = []
    for i, x in enumerate((-p.lock_bolt_offset, p.lock_bolt_offset)):
        # pocket face down onto the carriage top
        mounts.append((f"rail_lock_{i + 1}", "carriage",
                       _t(x, p.yoke_bottom_y + head_proud + h, p.rail_axis_z) @ _rx(90)))
    # under the carriage, pocket face up, holding the yaw nut
    mounts.append(("yaw", "carriage", _t(0.0, p.rail_top_y - nut_proud - h, 0.0) @ _rx(-90)))
    # outside the arm, pocket face toward it
    mounts.append(("pitch", "yoke", _t(sx * (p.arm_outer_x + head_proud + h), 0.0, 0.0) @ _ry(-sx * 90)))
    return mounts


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
        for suffix, rides, local in knob_mounts(p, side):
            frame = carriage if rides == "carriage" else yoke
            out[f"knob_{side}_{suffix}"] = ("knob", frame @ local, f"{side}.{rides}")
    return out


def stand_matrices(p: Mount, pose: Pose):
    """The brackets under the rail ends, and for the monitor stand the rear arms and knobs."""
    f = p.fasteners
    out = {}
    L = p.rail_length / 2
    for side, sx in SIDES.items():
        centre = _t(sx * p.bracket_centre_x, 0.0, 0.0)
        if pose.stand == "desk":
            out[f"desk_foot_{side}"] = ("desk_foot", centre, "static")
            continue
        out[f"monitor_clamp_{side}"] = (f"monitor_clamp_{side}", centre, "static")
        # The arm sits on the ear's outer face; its leg's felt touches the monitor back.
        leg_z = p.monitor_front_z - pose.monitor_depth - p.felt_thickness
        outer = L + p.clamp_ear
        x0 = outer if sx > 0 else -outer - p.arm_plate
        out[f"clamp_arm_{side}"] = ("clamp_arm", _t(x0, 0.0, leg_z), "static")
        head_proud = f.m4_head_height - p.knob_pocket_depth
        knob_x = sx * (outer + p.arm_plate + head_proud + p.knob_height)
        out[f"knob_{side}_clamp"] = ("knob", _t(knob_x, p.clamp_bolt_y, p.clamp_bolt_z) @ _ry(-sx * 90), "static")
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
