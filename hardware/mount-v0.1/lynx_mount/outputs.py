"""Print orientation, STL files, the editable .blend scene and rendered previews."""

import math
import struct

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import assembly as asm
from .params import Mount

# How each part lies on the bed, as a rotation from its local rig-oriented frame into
# Blender's Z-up print frame. "Up" names the rig direction that points away from the bed.
_UP_Y = asm.RIG_TO_BLENDER                                   # rig +Y up
_UP_NEG_Y = Matrix.Rotation(math.pi, 4, "X") @ asm.RIG_TO_BLENDER  # rig -Y up (upside down)
_UP_Z = Matrix.Identity(4)                                   # rig +Z up (rear face on the bed)

PRINTS = {
    # part: (print rotation, quantity, why this orientation)
    "base": (_UP_Y, 1, "flat underside on the bed; tunnel and cable channel bridge, no supports"),
    "carriage_left": (_UP_NEG_Y, 1, "upside down: the key points up and the top face with the yaw scale lies on the bed"),
    "carriage_right": (_UP_NEG_Y, 1, "upside down: the key points up and the top face with the yaw scale lies on the bed"),
    "yoke_left": (_UP_Y, 1, "base on the bed; the pitch hole is a teardrop pointing up"),
    "yoke_right": (_UP_Y, 1, "base on the bed; the pitch hole is a teardrop pointing up"),
    "camera_holder": (_UP_Z, 2, "rear plate on the bed; fins have 45-degree undersides, pitch hole is a teardrop"),
    "knob": (_UP_Z, 8, "hex pocket up"),
    "coupon_pcb": (_UP_Z, 1, "as the holder"),
    "coupon_rail": (_UP_Y, 1, "as the base"),
    "coupon_slider": (_UP_NEG_Y, 1, "as the carriage"),
}


def print_matrix(ob, rotation):
    """Rotation, then a shift that centres the part on the bed origin and rests it on z = 0."""
    vs = np.array([v.co[:] for v in ob.data.vertices])
    R = np.array(rotation)[:3, :3]
    rv = vs @ R.T
    lo, hi = rv.min(axis=0), rv.max(axis=0)
    shift = Vector((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))
    return Matrix.Translation(shift) @ rotation


def write_stl(path, ob, matrix):
    """Binary STL in millimetres."""
    me = ob.data
    me.calc_loop_triangles()
    M = np.array(matrix)
    vs = np.array([v.co[:] for v in me.vertices]) @ M[:3, :3].T + M[:3, 3]
    tris = np.array([t.vertices[:] for t in me.loop_triangles])
    a, b, c = vs[tris[:, 0]], vs[tris[:, 1]], vs[tris[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    with open(path, "wb") as fh:
        fh.write(b"LYNX SIGHT mount v0.1".ljust(80, b" "))
        fh.write(struct.pack("<I", len(tris)))
        for i in range(len(tris)):
            fh.write(struct.pack("<12fH", *n[i], *a[i], *b[i], *c[i], 0))


# ------------------------------------------------------------------ scene
COLOURS = {
    "base": (0.12, 0.12, 0.13, 1), "carriage": (0.85, 0.42, 0.10, 1), "yoke": (0.18, 0.40, 0.75, 1),
    "camera_holder": (0.80, 0.80, 0.78, 1), "knob": (0.05, 0.05, 0.05, 1), "coupon": (0.55, 0.70, 0.35, 1),
    "ref_pcb": (0.05, 0.35, 0.15, 1), "ref_lens": (0.02, 0.02, 0.02, 1), "ref_rear_parts": (0.6, 0.55, 0.2, 1),
    "ref_connector": (0.9, 0.9, 0.9, 1), "ref_cable_keepout": (0.9, 0.1, 0.1, 0.35), "ref_fov": (1.0, 0.85, 0.1, 0.08),
}


def material(key):
    name = f"mat_{key}"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    rgba = next((v for k, v in COLOURS.items() if key.startswith(k)), (0.5, 0.5, 0.5, 1))
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = 0.55
    if rgba[3] < 1:
        bsdf.inputs["Alpha"].default_value = rgba[3]
    mat.diffuse_color = rgba
    return mat


def _collection(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def _instance(name, mesh_ob, matrix, coll, colour_key):
    ob = bpy.data.objects.new(name, mesh_ob.data)
    ob.matrix_world = matrix
    if not mesh_ob.data.materials:
        mesh_ob.data.materials.append(material(colour_key))
    coll.objects.link(ob)
    return ob


def build_scene(p: Mount, parts, refs, fov, pose, explode_offset=(420.0, 0.0, 0.0)):
    """Collections: Assembly (posed), Camera reference, Exploded, Print layout."""
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"

    root = Matrix(asm.RIG_TO_BLENDER)
    library = _collection("Part meshes")  # the source objects, one per printable part
    for ob in list(parts.values()) + list(refs.values()) + [fov]:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        library.objects.link(ob)
        ob.data.materials.clear()
        ob.data.materials.append(material(ob.name))
    library.hide_render = True
    library.hide_viewport = True
    bpy.context.view_layer.layer_collection.children[library.name].exclude = True

    assembly = _collection("Assembly")
    reference = _collection("Camera reference")
    keepouts = _collection("Keep-outs and FOV")
    exploded = _collection("Exploded")
    layout = _collection("Print layout")

    inst = asm.instance_matrices(p, pose)
    for name, (key, M, _group) in inst.items():
        _instance(name, parts[key], root @ M, assembly, key)
    for side, M in asm.camera_matrices(p, pose).items():
        for k in ("pcb", "lens", "rear_parts", "connector"):
            _instance(f"cam_{side}_{k}", refs[k], root @ M, reference, f"ref_{k}")
        _instance(f"cam_{side}_cable_keepout", refs["cable_keepout"], root @ M, keepouts, "ref_cable_keepout")
        _instance(f"cam_{side}_fov", fov, root @ M, keepouts, "ref_fov")

    # Exploded: the same instances at zero angles, each stack layer lifted.
    zero = asm.Pose(pose.baseline)
    shift = Matrix.Translation(explode_offset)
    for name, (key, M, group) in asm.instance_matrices(p, zero).items():
        layer = group.split(".")[-1]
        lift = asm.EXPLODE.get("holder" if layer == "holder" else layer, Matrix.Identity(4))
        if key == "knob":
            lift = lift @ Matrix.Translation((0, 14 if "rail_lock" in name else -14 if "yaw" in name else 0, 0))
            if "pitch" in name:
                lift = asm.EXPLODE["yoke"] @ Matrix.Translation((18 if "right" in name else -18, 0, 0))
        _instance(f"x_{name}", parts[key], shift @ root @ lift @ M, exploded, key)
    for side, M in asm.camera_matrices(p, zero).items():
        for k in ("pcb", "lens", "rear_parts", "connector"):
            _instance(f"x_cam_{side}_{k}", refs[k], shift @ root @ asm.EXPLODE["camera"] @ M, exploded, f"ref_{k}")

    # Print layout: one of each part as it lies on the bed, in a row.
    x = -300.0
    for key, (rot, qty, _why) in PRINTS.items():
        if key not in parts:
            continue
        M = print_matrix(parts[key], rot)
        size = _size(parts[key], M)
        x += size[0] / 2
        _instance(f"print_{key}", parts[key], Matrix.Translation((x, -300.0, 0.0)) @ M, layout, key)
        x += size[0] / 2 + 15.0
    return dict(assembly=assembly, reference=reference, keepouts=keepouts, exploded=exploded, layout=layout)


def _size(ob, M):
    A = np.array(M)
    vs = np.array([v.co[:] for v in ob.data.vertices]) @ A[:3, :3].T
    return vs.max(axis=0) - vs.min(axis=0)


# ------------------------------------------------------------------ renders
def _look(cam, target, location):
    cam.location = location
    direction = Vector(target) - Vector(location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def render_views(path_prefix, collections, desk_z, samples=48, resolution=(1280, 800)):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.compression = 90

    world = bpy.data.worlds.new("studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.92, 0.93, 0.95, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    scene.world = world
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(40), math.radians(15), math.radians(-30))
    scene.collection.objects.link(sun)
    floor_me = bpy.data.meshes.new("floor")
    floor_me.from_pydata([(-2000, -2000, 0), (2000, -2000, 0), (2000, 2000, 0), (-2000, 2000, 0)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("floor", floor_me)
    floor.data.materials.append(material("floor"))
    scene.collection.objects.link(floor)

    cam = bpy.data.objects.new("render_camera", bpy.data.cameras.new("render_camera"))
    cam.data.lens = 50
    cam.data.clip_end = 10000
    scene.collection.objects.link(cam)
    scene.camera = cam

    def show(*names):
        for k, c in collections.items():
            c.hide_render = k not in names

    def place_floor(z):
        floor.location.z = z

    views = []
    desk = desk_z
    # Blender frame: rig (x, y, z) -> (x, -z, y). The user sits at -Y looking +Y.
    jobs = [
        ("assembly_iso", ("assembly", "reference"), (0, 25, -25), (-210, -300, 150), desk),
        ("assembly_user_view", ("assembly", "reference"), (0, 25, -20), (0, -420, 0), desk),
        ("assembly_side", ("assembly", "reference"), (0, 25, -25), (-330, 25, -5), desk),
        ("assembly_rear", ("assembly", "reference"), (0, 25, -25), (190, 330, 170), desk),
        ("assembly_fov_top", ("assembly", "reference", "keepouts"), (0, -120, -20), (0, -120, 800), desk),
        ("exploded_iso", ("exploded",), (420, 20, 10), (230, -300, 230), desk),
        ("print_layout", ("layout",), (91, -300, 0), (91, -1180, 760), 0.0),
    ]
    for name, cols, target, loc, floor_z in jobs:
        show(*cols)
        place_floor(floor_z - 0.01)
        _look(cam, target, loc)
        scene.render.filepath = f"{path_prefix}{name}.png"
        bpy.ops.render.render(write_still=True)
        views.append(scene.render.filepath)
    show("assembly", "reference", "keepouts", "exploded", "layout")
    return views
