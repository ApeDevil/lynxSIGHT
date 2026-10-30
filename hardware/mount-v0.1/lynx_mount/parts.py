"""The printable parts of mount v0.1, each built in its own local frame.

Local frames are rig-oriented (Y up, Z toward the user) so the assembly only translates
and rotates them:
  holder, camera   origin at the optical centre
  yoke, carriage   origin on the yaw axis (x = 0, z = 0); Y is the rig's absolute Y
  base             the rig frame itself (x = 0 between the cameras)
  knob             axis +Z, bore at the origin, the hex pocket on the z = height face
Sided parts are built for cam_right (outer side = +X) and mirrored for cam_left.
"""

import math

from . import mesh as m
from .params import Mount


def _side(name, side):
    return f"{name}_{side}"


# ------------------------------------------------------------------ camera holder
def holder(p: Mount, name="camera_holder"):
    f = p.fasteners
    wi, wo, h = p.wall_inner_x, p.wall_outer_x, p.holder_height / 2
    zb, zf = p.rear_plate_back_z, p.rear_plate_front_z
    adds = [m.box(-wo, wo, -h, h, zb, zf)]
    cuts = [m.box(-p.rear_window / 2, p.rear_window / 2, -p.rear_window / 2, p.rear_window / 2, zb - 1, zf + 1)]
    for sx in (-1, 1):
        x0, x1 = sorted((sx * wi, sx * wo))
        adds.append(m.box(x0, x1, -h, h, zb, 0.0))
        adds.append(m.cylinder(p.holder_front_radius, x0, x1, "X", (0.0, 0.0)))
        # Pitch index fin: front face on the plane through the pitch axis, 45-degree underside.
        r0, r1, reach = p.index_fin
        fin = [(sx * wo, 0.0), (sx * (wo + reach), 0.0), (sx * (wo + reach), -1.0), (sx * wo, -1.0 - reach)]
        adds.append(m.extrude(fin if sx > 0 else fin[::-1], r0, r1, "Y"))
        # Nut pocket on the inner face, flat side up when printing: a short bridge, 60-degree sides.
        n0, n1 = sorted((sx * (wi - 0.01), sx * (wi + p.pitch_nut_depth)))
        cuts.append(m.extrude(m.hexagon(f.m4_hex_pocket_af, vertex_dir=0.0), n0, n1, "X"))
    cuts.append(m.extrude(m.teardrop(f.m4_clearance / 2, tip_dir=math.pi / 2), -wo - 1, wo + 1, "X"))
    hp = p.camera.hole_pitch_outer.value / 2
    for x in (-hp, hp):
        for y in (-hp, hp):
            adds.append(m.cylinder(p.standoff_diameter / 2, zf - 0.01, p.pcb_back_z, "Z", (x, y)))
            cuts.append(m.cylinder(f.m2_clearance / 2, zb - 1, p.pcb_back_z + 1, "Z", (x, y), segments=24))
            cuts.append(m.extrude(m.hexagon(f.m2_hex_pocket_af), zb - 1, zb + f.m2_nut_thickness + 0.2, "Z", (x, y)))
    # 45-degree chamfers on the rear vertical edges: the swept corner is what limits how
    # close the two cameras can stand when both turn outward.
    c = p.holder_rear_chamfer
    for sx in (-1, 1):
        tri = [(sx * (wo + 1), zb - 1), (sx * (wo - c), zb - 1), (sx * (wo + 1), zb + c + 1)]
        cuts.append(m.extrude(tri if sx < 0 else tri[::-1], -h - 1, h + 1, "Y"))
    # Cable-tie slot pairs below and above the window: tie the cable to the rear plate.
    sl, sw = p.tie_slot
    ym = (p.rear_window / 2 + h) / 2
    for y in (-ym, ym):
        for x in (-6.0, 6.0):
            cuts.append(m.box(x - sl / 2, x + sl / 2, y - sw / 2, y + sw / 2, zb - 1, zf + 1))
    return m.solid(name, adds, cuts)


# ------------------------------------------------------------------ yoke
def yoke(p: Mount, side="right"):
    f = p.fasteners
    yb, yt = p.yoke_bottom_y, p.yoke_top_y
    ai, ao, w = p.arm_inner_x, p.arm_outer_x, p.arm_width / 2
    boss = w
    adds = [
        m.cylinder(p.yoke_disk_radius, yb, yt, "Y", (0.0, 0.0)),
        m.box(0.0, ao, yb, yt, -w, w),
        m.box(ai, ao, yb, 0.0, -w, w),
        m.cylinder(boss, ai, ao, "X", (0.0, 0.0)),
        # Gusset on the outer face, below the knob.
        m.extrude([(ao - 0.01, yb), (ao + 8.0, yb), (ao - 0.01, yb + 20.0)], -w, w, "Z"),
        # Yaw pointer on the carriage surface, toward the user.
        m.extrude([(-3.0, p.yoke_disk_radius - 0.5), (3.0, p.yoke_disk_radius - 0.5), (0.0, p.yaw_pointer_reach)],
                  yb, yb + 2.0, "Y"),
    ]
    cuts = [
        m.cylinder(f.m4_clearance / 2, yb - 1, yt + 1, "Y", (0.0, 0.0), segments=32),
        m.extrude(m.hexagon(f.m4_hex_pocket_af, vertex_dir=0.0), yt - p.yaw_head_pocket_depth, yt + 1, "Y"),
        m.extrude(m.teardrop(f.m4_clearance / 2, tip_dir=0.0), ai - 1, ao + 1, "X"),  # tip toward +Y
    ]
    # Pitch scale: radial notches on the boss rim, read against the holder's index fin.
    # Positive pitch rotates the holder by -pitch about X, which carries the fin toward -Z.
    for deg in p.angle_ticks(p.pitch_range):
        major = deg % 10 == 0
        x0 = ai - 0.5 if major else ao - 3.0
        t = m.box(x0, ao + 1, boss - p.printing.engrave_depth, boss + 1, -0.3, 0.3)
        m.transform(t, m.rotation("X", -deg))
        cuts.append(t)
    # Positive-side marker: a dimple on the rim beyond +20 degrees.
    d = m.cylinder(0.9, boss - p.printing.engrave_depth, boss + 1, "Y", (ao - 1.5, 0.0), segments=16)
    m.transform(d, m.rotation("X", -(p.pitch_range - 2.5)))
    cuts.append(d)
    ob = m.solid(_side("yoke", side), adds, cuts)
    if side == "left":
        _mirror_x(ob)
    return ob


def _mirror_x(ob):
    import bmesh
    from mathutils import Matrix
    ob.data.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


# ------------------------------------------------------------------ carriage
def carriage(p: Mount, side="right"):
    f = p.fasteners
    sign = 1 if side == "right" else -1
    y0, y1 = p.rail_top_y, p.yoke_bottom_y
    half = p.carriage_width / 2
    zb, zf = p.carriage_back_z, p.carriage_front
    zc = (zb + zf) / 2
    plate = m.extrude([(x, z + zc) for x, z in m.rounded_rect(p.carriage_width, zf - zb, 3.0)], y0, y1, "Y")
    kw = p.slot_width / 2 - p.printing.sliding_clearance
    key = m.box(-half + 2, half - 2, y0 - p.key_height, y0 + 0.01, p.rail_axis_z - kw, p.rail_axis_z + kw)
    cuts = [m.cylinder(f.m4_clearance / 2, y0 - 5, y1 + 1, "Y", (x, p.rail_axis_z), segments=32)
            for x in (-p.lock_bolt_offset, p.lock_bolt_offset)]
    cuts.append(m.cylinder(f.m4_clearance / 2, y0 - 1, y1 + 1, "Y", (0.0, 0.0), segments=32))
    e = p.printing.engrave_depth
    # Yaw scale around the pivot. For cam_right positive yaw turns +Z toward -X (rotation
    # by -yaw about Y); for cam_left by +yaw. The dimple marks the positive side.
    r0, r1 = p.yaw_tick_radii
    for deg in p.angle_ticks(p.yaw_range):
        major = deg % 10 == 0
        t = m.box(-0.3, 0.3, y1 - e, y1 + 1, r0, r1 if major else (r0 + r1) / 2)
        m.transform(t, m.rotation("Y", -sign * deg))
        cuts.append(t)
    d = m.cylinder(0.9, y1 - e, y1 + 1, "Y", (0.0, r1 - 0.5), segments=16)
    m.transform(d, m.rotation("Y", -sign * (p.yaw_range - 2.5)))
    cuts.append(d)
    # Baseline index: a V notch in the back edge on the camera axis.
    cuts.append(m.extrude([(-1.5, zb - 0.01), (0.0, zb + 2.0), (1.5, zb - 0.01)][::-1], y0 - 1, y1 + 1, "Y"))
    # Side letter on the front face.
    letter = m.text("R" if side == "right" else "L", 4.0, 1.2, name="letter")
    m.transform(letter, m.translation(0.0, (y0 + y1) / 2, zf - 0.6))
    cuts.append(letter)
    return m.solid(_side("carriage", side), [plate, key], cuts)


# ------------------------------------------------------------------ base with rail
def base(p: Mount, name="base"):
    f = p.fasteners
    L = p.rail_length / 2
    zr, d = p.rail_axis_z, p.rail_depth / 2
    yd, yt = p.desk_y, p.rail_top_y
    adds = [m.box(-L, L, yd, yt, zr - d, zr + d)]
    fz0, fz1 = p.foot_z
    for sx in (-1, 1):
        cx = sx * (L - p.foot_length / 2)
        outline = [(x + cx, z + (fz0 + fz1) / 2) for x, z in m.rounded_rect(p.foot_length, fz1 - fz0, 6.0)]
        adds.append(m.extrude(outline, yd, yd + p.foot_thickness, "Y"))
    slot_end = L - 3.0
    cuts = [
        m.box(-slot_end, slot_end, yt - p.rail_web - 0.5, yt + 1, zr - p.slot_width / 2, zr + p.slot_width / 2),
        m.box(-L - 1, L + 1, yt - p.rail_web - p.tunnel_height, yt - p.rail_web, zr - p.tunnel_width / 2, zr + p.tunnel_width / 2),
        m.box(-L - 1, L + 1, yd - 1, yd + p.cable_channel[1], zr - p.cable_channel[0] / 2, zr + p.cable_channel[0] / 2),
    ]
    e = p.printing.engrave_depth
    zback = zr - d
    for b, x in p.baseline_ticks():
        length = 5.0 if b == p.baseline_nominal else 3.5 if b % 10 == 0 else 2.0
        for sx in (-1, 1):
            cuts.append(m.box(sx * x - 0.3, sx * x + 0.3, yt - e, yt + 1, zback - 1, zback + length))
        if b % 20 == 0:
            for sx in (-1, 1):
                t = m.text(f"{int(b)}", 4.5, 1.2, name="num")
                m.transform(t, m.rotation("Y", 180))
                m.transform(t, m.translation(sx * x, yt - 6.0, zback + 0.6))
                cuts.append(t)
    # Cable-tie slot pairs behind the rail on each foot, for a cable running along Z.
    sl, sw = p.tie_slot
    for sx in (-1, 1):
        for dx in (-5.0, 5.0):
            x = sx * (L - p.foot_length / 2) + dx
            cuts.append(m.box(x - sw / 2, x + sw / 2, yd - 1, yd + p.foot_thickness + 1, fz0 + 18 - sl / 2, fz0 + 18 + sl / 2))
    label = m.text("SIGHT v0.1", 4.0, 1.2, name="label")
    m.transform(label, m.rotation("X", -90))  # flat on the right foot, readable from the user's side
    m.transform(label, m.translation(L - p.foot_length / 2, yd + p.foot_thickness - e, fz1 - 8.0))
    cuts.append(label)
    return m.solid(name, adds, cuts)


# ------------------------------------------------------------------ knob
def knob(p: Mount, name="knob"):
    f = p.fasteners
    r = p.knob_diameter / 2
    n = 192
    outline = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r - 1.4 * (0.5 - 0.5 * math.cos(p.knob_lobes * a))
        outline.append((rr * math.cos(a), rr * math.sin(a)))
    body = m.extrude(outline, 0.0, p.knob_height, "Z")
    cuts = [
        m.cylinder(f.m4_clearance / 2, -1, p.knob_height + 1, "Z", segments=32),
        m.extrude(m.hexagon(f.m4_hex_pocket_af), p.knob_height - p.knob_pocket_depth, p.knob_height + 1, "Z"),
    ]
    return m.solid(name, [body], cuts)


# ------------------------------------------------------------------ fit coupons
def coupon_pcb(p: Mount, name="coupon_pcb"):
    """The holder's rear plate and standoffs, both hole patterns, and one pitch joint.

    Print it first: the PCB must sit on the standoffs with M2 screws through either
    pattern, an M2 and an M4 nut must press into their pockets, and an M4 bolt must pass
    the horizontal teardrop hole.
    """
    f = p.fasteners
    wo, h = p.wall_outer_x, p.holder_height / 2
    zb, zf = p.rear_plate_back_z, p.rear_plate_front_z
    adds = [m.box(-wo, wo, -h, h, zb, zf)]
    cuts = [m.box(-p.rear_window / 2, p.rear_window / 2, -p.rear_window / 2, p.rear_window / 2, zb - 1, zf + 1)]
    hp = p.camera.hole_pitch_outer.value / 2
    for x in (-hp, hp):
        for y in (-hp, hp):
            adds.append(m.cylinder(p.standoff_diameter / 2, zf - 0.01, p.pcb_back_z, "Z", (x, y)))
            cuts.append(m.cylinder(f.m2_clearance / 2, zb - 1, p.pcb_back_z + 1, "Z", (x, y), segments=24))
            cuts.append(m.extrude(m.hexagon(f.m2_hex_pocket_af), zb - 1, zb + f.m2_nut_thickness + 0.2, "Z", (x, y)))
    ip = p.camera.hole_pitch_inner.value / 2
    for x in (-ip, ip):
        for y in (-ip, ip):
            cuts.append(m.cylinder(f.m2_clearance / 2, zb - 1, zf + 1, "Z", (x, y), segments=24))
    # One pitch joint: a wall section with the teardrop hole and the inner-face nut pocket.
    wi = p.wall_inner_x
    adds.append(m.box(wi, wo, -8.0, 8.0, zb, zb + 16.0))
    zc = zb + 9.0
    cuts.append(m.extrude(m.teardrop(f.m4_clearance / 2, tip_dir=math.pi / 2), wi - 1, wo + 1, "X", (0.0, zc)))
    cuts.append(m.extrude(m.hexagon(f.m4_hex_pocket_af, vertex_dir=0.0), wi - 0.01, wi + p.pitch_nut_depth, "X", (0.0, zc)))
    return m.solid(name, adds, cuts)


def coupon_rail(p: Mount, length=30.0, name="coupon_rail"):
    """A slice of the rail profile: slot, nut tunnel and cable channel."""
    zr, d = p.rail_axis_z, p.rail_depth / 2
    yd, yt = p.desk_y, p.rail_top_y
    L = length / 2
    adds = [m.box(-L, L, yd, yt, zr - d, zr + d)]
    cuts = [
        m.box(-L + 3, L - 3, yt - p.rail_web - 0.5, yt + 1, zr - p.slot_width / 2, zr + p.slot_width / 2),
        m.box(-L - 1, L + 1, yt - p.rail_web - p.tunnel_height, yt - p.rail_web, zr - p.tunnel_width / 2, zr + p.tunnel_width / 2),
        m.box(-L - 1, L + 1, yd - 1, yd + p.cable_channel[1], zr - p.cable_channel[0] / 2, zr + p.cable_channel[0] / 2),
    ]
    return m.solid(name, adds, cuts)


def coupon_slider(p: Mount, length=24.0, name="coupon_slider"):
    """A carriage slice with the key and one lock-bolt hole, to try on coupon_rail."""
    zr, d = p.rail_axis_z, p.rail_depth / 2
    y0, y1 = p.rail_top_y, p.yoke_bottom_y
    L = length / 2
    kw = p.slot_width / 2 - p.printing.sliding_clearance
    adds = [m.box(-L, L, y0, y1, zr - d, zr + d),
            m.box(-L + 1, L - 1, y0 - p.key_height, y0 + 0.01, zr - kw, zr + kw)]
    cuts = [m.cylinder(p.fasteners.m4_clearance / 2, y0 - 5, y1 + 1, "Y", (0.0, zr), segments=32)]
    return m.solid(name, adds, cuts)


# ------------------------------------------------------------------ camera reference model
def camera_reference(p: Mount):
    """Reference volumes of one B0332, in the holder frame, for fit checks and renders.

    Returns {name: object}. Dimensions marked ASSUMED in params are not measured.
    The PCB stands 0.01 mm proud of the standoffs so contact does not count as overlap.
    """
    c = p.camera
    hs = p.pcb_half
    zf, zb = p.pcb_front_z + 0.01, p.pcb_back_z + 0.01
    hp = c.hole_pitch_outer.value / 2
    pcb = m.solid("ref_pcb", [m.box(-hs, hs, -hs, hs, zb, zf)],
                  [m.cylinder(c.hole_diameter.value / 2, zb - 1, zf + 1, "Z", (x, y), segments=24)
                   for x in (-hp, hp) for y in (-hp, hp)])
    lh = c.lens_holder_size.value / 2
    lens = m.solid("ref_lens", [
        m.box(-lh, lh, -lh, lh, zf - 0.01, zf + c.lens_holder_height.value),
        m.cylinder(c.lens_barrel_diameter.value / 2, zf + c.lens_holder_height.value - 0.01,
                   zf + c.lens_length_from_pcb.value, "Z"),
    ])
    rh = c.rear_component_height.value
    rear = m.solid("ref_rear_parts", [m.box(-hs + 0.5, hs - 0.5, -hs + 0.5, hs - 0.5, zb - rh, zb - 0.01)],
                   [m.cylinder(3.25, zb - rh - 1, zb + 1, "Z", (x, y)) for x in (-hp, hp) for y in (-hp, hp)])
    cx, cy, cd = c.connector_size
    conn = m.box(-cx / 2, cx / 2, -cy / 2, cy / 2, zb - cd, zb - 0.01, name="ref_connector")
    # Plug and the first bend of the USB cable: what must stay clear for connector access.
    plug = m.box(-5.0, 5.0, -3.5, 3.5, zb - cd - 25.0, zb - cd, name="ref_cable_keepout")
    return {"pcb": pcb, "lens": lens, "rear_parts": rear, "connector": conn, "cable_keepout": plug}


def fov_frustum(p: Mount, length=400.0, name="ref_fov"):
    """The sensor's field of view as a pyramid from the lens front (ASSUMED position)."""
    import bmesh
    c = p.camera
    z0 = p.pcb_front_z + c.lens_length_from_pcb.value + 0.5
    tx = math.tan(math.radians(c.hfov_deg.value / 2))
    ty = math.tan(math.radians(c.vfov_deg / 2))
    bm = bmesh.new()
    apex = bm.verts.new((0.0, 0.0, z0))
    far = [bm.verts.new((sx * tx * length, sy * ty * length, z0 + length))
           for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for i in range(4):
        bm.faces.new((apex, far[i], far[(i + 1) % 4]))
    bm.faces.new(far[::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return m._object_from_bmesh(bm, name)
