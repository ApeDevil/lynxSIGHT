"""Solid primitives and exact booleans on Blender meshes.

Coordinates are given in the part's local rig-oriented frame (Y up, Z toward the user);
the assembly maps that frame into Blender's Z-up world once, at its root.
"""

import math

import bmesh
import bpy
from mathutils import Matrix

SEGMENTS = 64  # polygon count of a full circle; 64 keeps a 22 mm knob within 0.03 mm of round
_scratch = None


def _scratch_collection():
    global _scratch
    if _scratch is None or _scratch.name not in bpy.data.collections:
        _scratch = bpy.data.collections.new("_csg_scratch")
    if _scratch.name not in bpy.context.scene.collection.children:
        # Only objects in the scene are evaluated, and booleans need evaluated operands.
        bpy.context.scene.collection.children.link(_scratch)
    return _scratch


def _object_from_bmesh(bm, name):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    _scratch_collection().objects.link(ob)
    return ob


def circle(r, segments=SEGMENTS, phase=0.0):
    return [(r * math.cos(phase + 2 * math.pi * i / segments),
             r * math.sin(phase + 2 * math.pi * i / segments)) for i in range(segments)]


def hexagon(af, vertex_dir=math.pi / 2):
    """Hexagon with the given across-flats width and one vertex pointing along vertex_dir."""
    r = af / math.sqrt(3)
    return [(r * math.cos(vertex_dir + i * math.pi / 3), r * math.sin(vertex_dir + i * math.pi / 3))
            for i in range(6)]


def teardrop(r, tip_dir=math.pi / 2, segments=SEGMENTS):
    """Circle with a 90-degree pointed cap toward tip_dir, so a horizontal hole prints unsupported."""
    arc = [tip_dir + math.pi / 4 + (3 * math.pi / 2) * i / (segments - 1) for i in range(segments)]
    tip = (r * math.sqrt(2) * math.cos(tip_dir), r * math.sqrt(2) * math.sin(tip_dir))
    return [tip] + [(r * math.cos(a), r * math.sin(a)) for a in arc]


def rounded_rect(w, h, r, segments=16):
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for i in range(segments + 1):
            a = math.radians(a0 + 90 * i / segments)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def box(x0, x1, y0, y1, z0, z1, name="box"):
    return _oriented([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, "Z", (0, 0), name)


def cylinder(r, a0, a1, axis="Z", at=(0, 0), segments=SEGMENTS, name="cyl"):
    """Cylinder along `axis` from a0 to a1, centred at `at` in the two other coordinates.

    `at` is (x, y) for Z, (y, z) for X, (x, z) for Y — given in world terms here.
    """
    return _oriented(circle(r, segments), a0, a1, axis, at, name)


def _oriented(outline, a0, a1, axis, at, name):
    """Prism whose 2D outline is given in world coordinates of the plane normal to axis:
    Z: (x, y); X: (y, z); Y: (x, z)."""
    bm = bmesh.new()
    def place(u, v, w):
        if axis == "Z":
            return (u + at[0], v + at[1], w)
        if axis == "X":
            return (w, u + at[0], v + at[1])
        return (u + at[0], w, v + at[1])
    bottom = [bm.verts.new(place(u, v, a0)) for u, v in outline]
    top = [bm.verts.new(place(u, v, a1)) for u, v in outline]
    bm.faces.new(bottom)
    bm.faces.new(list(reversed(top)))
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((bottom[j], bottom[i], top[i], top[j]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _object_from_bmesh(bm, name)


def extrude(outline, a0, a1, axis="Z", at=(0, 0), name="extrude"):
    """Extrude a 2D outline given in world coordinates of the plane normal to `axis`
    (Z: (x, y); X: (y, z); Y: (x, z)) from a0 to a1 along it."""
    return _oriented(outline, a0, a1, axis, at, name)


def text(body, size, depth, name="text", align="CENTER"):
    """Flat text in the local XY plane, extruded from z=0 to z=depth, as a mesh object."""
    cu = bpy.data.curves.new(name, type="FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.extrude = depth / 2
    tmp = bpy.data.objects.new(name + "_curve", cu)
    _scratch_collection().objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    ob = bpy.data.objects.new(name, me)
    _scratch_collection().objects.link(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.translate(bm, vec=(0, 0, depth / 2), verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    return ob


def thread(r_major, pitch, depth, z0, z1, crest=0.125, root=0.125, chamfer=(True, True),
           segments=48, steps=16, name="thread"):
    """Threaded rod along +Z from z0 to z1, axis at the origin: a radially displaced grid
    with flat, closed ends, so it is a valid solid for booleans.

    The profile over one pitch is a crest flat, a flank, a root flat and a flank; with
    flank = depth / pitch of the pitch each flank is at 45 degrees, so the thread prints
    without support standing up. A chamfered end runs down to the minor radius at 45
    degrees. Used as it is for a screw, and grown by a clearance as the tap that cuts a
    threaded hole.
    """
    r_minor = r_major - depth
    flank = (1.0 - crest - root) / 2

    def profile(u):
        u %= 1.0
        if u < crest:
            return r_major
        if u < crest + flank:
            return r_major - depth * (u - crest) / flank
        if u < crest + flank + root:
            return r_minor
        return r_minor + depth * (u - crest - flank - root) / flank

    rows = max(2, int(math.ceil((z1 - z0) / (pitch / steps))) + 1)
    bm = bmesh.new()
    grid = []
    for k in range(rows):
        z = z0 + (z1 - z0) * k / (rows - 1)
        ring = []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            r = profile(z / pitch - i / segments)
            if chamfer[0]:
                r = min(r, r_minor + (z - z0))
            if chamfer[1]:
                r = min(r, r_minor + (z1 - z))
            ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), z)))
        grid.append(ring)
    bm.faces.new(list(reversed(grid[0])))
    bm.faces.new(grid[-1])
    for k in range(rows - 1):
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((grid[k][i], grid[k][j], grid[k + 1][j], grid[k + 1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _object_from_bmesh(bm, name)


def frustum(r0, r1, a0, a1, axis="Z", at=(0, 0), segments=SEGMENTS, name="frustum"):
    """Truncated cone along `axis`, radius r0 at a0 and r1 at a1 (see cylinder for `at`)."""
    bm = bmesh.new()
    def place(u, v, w):
        if axis == "Z":
            return (u + at[0], v + at[1], w)
        if axis == "X":
            return (w, u + at[0], v + at[1])
        return (u + at[0], w, v + at[1])
    lo = [bm.verts.new(place(x, y, a0)) for x, y in circle(r0, segments)]
    hi = [bm.verts.new(place(x, y, a1)) for x, y in circle(r1, segments)]
    bm.faces.new(lo)
    bm.faces.new(list(reversed(hi)))
    for i in range(segments):
        j = (i + 1) % segments
        bm.faces.new((lo[j], lo[i], hi[i], hi[j]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _object_from_bmesh(bm, name)


def transform(ob, matrix):
    ob.data.transform(matrix)
    ob.data.update()
    return ob


def rotation(axis, deg):
    return Matrix.Rotation(math.radians(deg), 4, axis)


def translation(x, y, z):
    return Matrix.Translation((x, y, z))


def _apply_boolean(target, cutters, operation):
    if not cutters:
        return
    coll = bpy.data.collections.new("_operands")
    for c in cutters:
        coll.objects.link(c)
    mod = target.modifiers.new("csg", "BOOLEAN")
    mod.operation = operation
    mod.solver = "EXACT"
    mod.operand_type = "COLLECTION"
    mod.collection = coll
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(target.evaluated_get(dg))
    target.modifiers.remove(mod)
    old = target.data
    target.data = me
    bpy.data.meshes.remove(old)
    for c in cutters:
        m = c.data
        bpy.data.objects.remove(c)
        if m.users == 0:
            bpy.data.meshes.remove(m)
    bpy.data.collections.remove(coll)


def solid(name, adds, cuts=()):
    """Union of `adds`, minus `cuts`; consumes the operands and returns one mesh object."""
    adds = list(adds)
    base = adds[0]
    _apply_boolean(base, adds[1:], "UNION")
    _apply_boolean(base, list(cuts), "DIFFERENCE")
    base.name = name
    base.data.name = name
    bm = bmesh.new()
    bm.from_mesh(base.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-5)
    # Dissolving can leave a stray wire edge where a thread's tiny facet collapsed.
    loose = [e for e in bm.edges if not e.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="EDGES")
    bm.to_mesh(base.data)
    bm.free()
    return base


def detach(ob):
    """Remove an object from the scratch collection (before it is linked to a real one)."""
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    return ob
