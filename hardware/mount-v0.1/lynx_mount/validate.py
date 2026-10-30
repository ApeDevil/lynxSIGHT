"""CAD-level checks of mount v0.1. They establish geometry, not physical fit.

- mesh:      each printable part is closed, manifold, one body, positive volume
- print:     each part fits the bed in its print orientation; overhang and bridge areas
- fit:       the camera reference model sits in the holder without overlap
- motion:    no part collides with another across the adjustment ranges
- access:    the connector/cable keep-out and the field of view stay clear
- fasteners: every printed screw engages enough thread and has room for its tip
- ranges:    baseline, yaw and pitch limits are reachable on the rail and scales
"""

import math

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import assembly as asm
from .params import Mount, fastener_stacks

COS45 = math.cos(math.radians(45.0))


# ------------------------------------------------------------------ mesh helpers
class Geometry:
    """Triangulated vertices of a part in its local frame, transformable without bpy ops."""

    def __init__(self, ob):
        me = ob.data
        me.calc_loop_triangles()
        self.verts = np.array([v.co[:] for v in me.vertices], dtype=float)
        self.tris = [tuple(t.vertices) for t in me.loop_triangles]

    def tree(self, matrix=None):
        v = self.verts if matrix is None else self.transformed(matrix)
        return BVHTree.FromPolygons(v.tolist(), self.tris, all_triangles=True)

    def transformed(self, matrix):
        M = np.array(matrix)
        return self.verts @ M[:3, :3].T + M[:3, 3]


def mesh_health(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.edges.ensure_lookup_table()
    non_manifold = sum(not e.is_manifold for e in bm.edges)
    boundary = sum(e.is_boundary for e in bm.edges)
    degenerate = sum(f.calc_area() < 1e-8 for f in bm.faces)
    seen, islands = set(), 0
    for f in bm.faces:
        if f.index in seen:
            continue
        islands += 1
        stack = [f]
        seen.add(f.index)
        while stack:
            g = stack.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
    volume = bm.calc_volume(signed=True)
    bm.free()
    ok = non_manifold == 0 and boundary == 0 and islands == 1 and volume > 0 and degenerate == 0
    return dict(ok=ok, non_manifold_edges=non_manifold, boundary_edges=boundary,
                degenerate_faces=degenerate, bodies=islands, volume_cm3=round(volume / 1000, 2))


def print_report(ob, bed_xyz, margin=0.0, max_overhang_deg=45.0):
    """Analyse a mesh already in print orientation (Z up, resting on z = 0)."""
    me = ob.data
    vs = np.array([v.co[:] for v in me.vertices])
    lo, hi = vs.min(axis=0), vs.max(axis=0)
    size = hi - lo
    limit = -math.cos(math.radians(90.0 - max_overhang_deg))  # n_z below this is steeper than allowed
    overhang = bridge = 0.0
    for f in me.polygons:
        if f.center.z < lo[2] + 0.05:
            continue  # on the bed
        nz = f.normal.z
        if nz < -0.999:
            bridge += f.area
        elif nz < limit - 1e-3:
            overhang += f.area
    bx, by, bz = bed_xyz[0] - 2 * margin, bed_xyz[1] - 2 * margin, bed_xyz[2]
    fits = bool(size[2] <= bz) and (bool(size[0] <= bx and size[1] <= by) or bool(size[1] <= bx and size[0] <= by))
    return dict(fits_bed=fits, size_mm=[round(float(s), 2) for s in size],
                steep_overhang_mm2=round(overhang, 1), bridge_mm2=round(bridge, 1))


# ------------------------------------------------------------------ assembly checks
def _overlaps(a, b):
    return len(a.overlap(b)) > 0


def _min_distance(geom_a, matrix_a, tree_b, sample=None):
    pts = geom_a.transformed(matrix_a)
    if sample and len(pts) > sample:
        pts = pts[:: max(1, len(pts) // sample)]
    best = math.inf
    for v in pts:
        hit = tree_b.find_nearest(Vector(v))
        if hit[0] is not None:
            best = min(best, hit[3])
    return best


# Pairs that touch by design (bearing faces), so their surfaces may coincide.
DESIGNED_CONTACT = {
    frozenset({"rail", "carriage_left"}), frozenset({"rail", "carriage_right"}),
    frozenset({"carriage_left", "yoke_left"}), frozenset({"carriage_right", "yoke_right"}),
}

REF_HARD = ("pcb", "lens", "rear_parts", "connector")


def stand_configs(p: Mount):
    """(stand, monitor depth) combinations the sweep covers: the desk, and the monitor
    clamp at both ends of its depth range."""
    d0, d1 = p.monitor_depth_range
    return [("desk", 30.0), ("monitor", d0), ("monitor", d1)]


def sweep_poses(p: Mount):
    baselines = sorted({p.baseline_min, p.baseline_nominal, p.baseline_max})
    yaws = p.angle_ticks(p.yaw_range)  # every scale step
    pitches = [-p.pitch_range, -p.pitch_range / 2, 0.0, p.pitch_range / 2, p.pitch_range]
    poses = []
    for stand, depth in stand_configs(p):
        def pose(b, l, r):
            return asm.Pose(b, l, r, stand=stand, monitor_depth=depth)
        for b in baselines:
            for y in yaws:
                for pt in pitches:
                    s = asm.Setting(y, pt)
                    poses.append(pose(b, s, s))
            for pt in pitches:  # both turned the same way (one in, one out)
                poses.append(pose(b, asm.Setting(p.yaw_range, pt), asm.Setting(-p.yaw_range, pt)))
                poses.append(pose(b, asm.Setting(-p.yaw_range, pt), asm.Setting(p.yaw_range, pt)))
    return poses


def check_assembly(p: Mount, part_objects, ref_objects, fov_object, monitor_objects):
    """monitor_objects: {depth: monitor reference object} for every depth in stand_configs."""
    geoms = {k: Geometry(o) for k, o in part_objects.items()}
    monitors = {d: Geometry(o) for d, o in monitor_objects.items()}
    refs = {k: Geometry(o) for k, o in ref_objects.items()}
    fov = Geometry(fov_object)

    result = {"fit": {}, "motion": {"poses": 0, "collisions": []},
              "access": {"cable_keepout_hits": [], "fov_occlusions": []}}

    # Fit at zero angles: reference camera in the holder frame.
    holder_tree = geoms["camera_holder"].tree()
    for k in ("pcb", "lens", "rear_parts", "connector", "cable_keepout"):
        t = refs[k].tree()
        result["fit"][k] = dict(overlaps_holder=_overlaps(t, holder_tree),
                                min_clearance_mm=round(_min_distance(refs[k], np.eye(4), holder_tree), 2))

    # The collision test must see a collision it is known to exist: cameras closer than
    # the carriages are wide.
    probe = asm.instance_matrices(p, asm.Pose(p.carriage_width - 10.0))
    _, ml, _ = probe["carriage_left"]
    _, mr, _ = probe["carriage_right"]
    result["motion"]["self_test_detects_overlap"] = _overlaps(
        geoms["carriage_left"].tree(ml), geoms["carriage_right"].tree(mr))

    poses = sweep_poses(p)
    seen_collisions, seen_cable, seen_fov = set(), set(), set()
    for pose in poses:
        inst = asm.instance_matrices(p, pose)
        cams = asm.camera_matrices(p, pose)
        trees = {name: (geoms[key].tree(M), group) for name, (key, M, group) in inst.items()}
        if pose.stand == "monitor":
            trees["monitor"] = (monitors[pose.monitor_depth].tree(asm.monitor_matrix(p, pose)), "monitor")
        for side, M in cams.items():
            for k in REF_HARD:
                trees[f"camera_{side}_{k}"] = (refs[k].tree(M), f"{side}.holder")
        names = sorted(trees)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ta, ga = trees[a]
                tb, gb = trees[b]
                if ga == gb or frozenset({a, b}) in DESIGNED_CONTACT:
                    continue  # rigidly joined, or touching by design
                if _overlaps(ta, tb):
                    key = (a, b)
                    if key not in seen_collisions:
                        seen_collisions.add(key)
                        result["motion"]["collisions"].append(dict(a=a, b=b, pose=_pose_str(pose)))
        for side, M in cams.items():
            cable = refs["cable_keepout"].tree(M)
            frustum = fov.tree(M)
            for name, (t, group) in trees.items():
                if group.startswith(side) and group.endswith("holder"):
                    continue
                if name.startswith("camera_holder") and group.startswith(side):
                    continue
                if _overlaps(cable, t) and (side, name) not in seen_cable:
                    seen_cable.add((side, name))
                    result["access"]["cable_keepout_hits"].append(dict(camera=side, part=name, pose=_pose_str(pose)))
                if _overlaps(frustum, t):
                    k = (side, name, pose.baseline, pose.stand)
                    if k not in seen_fov:
                        seen_fov.add(k)
                        result["access"]["fov_occlusions"].append(dict(camera=side, part=name, pose=_pose_str(pose)))
        result["motion"]["poses"] += 1
    result["motion"]["ok"] = (not result["motion"]["collisions"]
                              and result["motion"]["self_test_detects_overlap"])
    result["fit"]["ok"] = not any(v["overlaps_holder"] for k, v in result["fit"].items() if isinstance(v, dict))
    return result


def _pose_str(pose):
    stand = "desk" if pose.stand == "desk" else f"monitor {pose.monitor_depth:g} mm deep"
    return (f"{stand}, baseline {pose.baseline:g}, left yaw {pose.left.yaw_deg:+g} pitch {pose.left.pitch_deg:+g}, "
            f"right yaw {pose.right.yaw_deg:+g} pitch {pose.right.pitch_deg:+g}")


# ------------------------------------------------------------------ parameter checks
def check_fasteners(p: Mount):
    stacks = fastener_stacks(p)
    f = p.fasteners
    ok = all(s["engagement"] >= f.min_engagement and s["tip_room"] >= 0 for s in stacks.values())
    return dict(ok=ok, thread=f"printed {f.major:g} mm, pitch {f.pitch:g}, 45-degree flanks",
                joints={k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in stacks.items()})


def check_ranges(p: Mount):
    L = p.rail_length / 2
    half = p.carriage_width / 2
    slot_end = L - 3.0
    findings = {
        "carriages_clear_at_min_baseline_mm": round(p.baseline_min - p.carriage_width, 2),
        "carriage_on_rail_at_max_baseline_mm": round(L - (p.baseline_max / 2 + half), 2),
        "lock_bolt_in_slot_at_max_baseline_mm": round(slot_end - (p.baseline_max / 2 + p.lock_bolt_offset) - p.fasteners.shank_clearance / 2, 2),
        "standoffs_clear_rear_parts_mm": round(p.standoff_height - p.camera.rear_component_height.value, 2),
        "yaw_knob_clear_of_foot_mm": round(p.rail_top_y - asm.SEAT - p.knob_height
                                           - (p.surface_y + p.foot_thickness), 2),
        "optical_axis_above_support_surface_mm": round(-p.surface_y, 1),
        "monitor_depth_range_mm": [round(v, 1) for v in p.monitor_depth_range],
        "baseline_scale_ticks": [b for b, _ in p.baseline_ticks()],
    }
    findings["user_view_on_monitor"] = user_view(p)
    ok = all(v >= 0 for k, v in findings.items() if k.endswith("_mm") and not isinstance(v, list))
    ok = ok and findings["user_view_on_monitor"]["ok"]
    findings["ok"] = ok
    return findings


def user_view(p: Mount):
    """Can one pitch setting keep every expected eye position inside the vertical FOV when
    the rig sits on the monitor? Angles are below the horizontal, from the optical centre."""
    lens_above_top = -(p.surface_y - p.felt_thickness)
    angles = [math.degrees(math.atan2(lens_above_top - h, d))
              for h in p.eye_above_monitor_top for d in p.user_distance]
    lo, hi = min(angles), max(angles)
    half = p.camera.vfov_deg / 2
    pitch = -(lo + hi) / 2  # aim at the middle of the span
    ok = (hi - lo) <= 2 * half and abs(pitch) <= p.pitch_range
    return dict(ok=ok, eyes_below_horizontal_deg=[round(lo, 1), round(hi, 1)],
                suggested_pitch_deg=round(pitch, 1), vfov_deg=round(p.camera.vfov_deg, 1),
                margin_deg=round(half - (hi - lo) / 2, 1))
