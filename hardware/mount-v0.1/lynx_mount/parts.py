"""The printable parts of mount v0.1, each built in its own local frame.

Local frames are rig-oriented (Y up, Z toward the user) so the assembly only translates
and rotates them:
  holder, camera   origin at the optical centre
  yoke, carriage   origin on the yaw axis (x = 0, z = 0); Y is the rig's absolute Y
  base             the rig frame itself (x = 0 between the cameras)
  screw            axis +Z, the head's bearing face at z = 0, the head below it
  nut              axis +Z, from z = 0 to its thickness, one corner toward +Y
Sided parts are built for cam_right (outer side = +X) and mirrored for cam_left.
"""

import math

from . import mesh as m
from .params import Mount


def _side(name, side):
    return f"{name}_{side}"


def threaded_hole(p: Mount, a0, a1, axis="Z", at=(0.0, 0.0), mouths=(True, True)):
    """Cuts for a printed internal thread from a0 to a1 along `axis`, with 45-degree
    lead-in countersinks at the open ends. Print it with the axis vertical."""
    f = p.fasteners
    tap = m.thread(z0=a0 - 1.0, z1=a1 + 1.0, chamfer=(False, False), name="tap", **f.tap())
    if axis != "Z" or at != (0.0, 0.0):
        R = {"Z": m.rotation("Z", 0), "X": m.rotation("Y", 90), "Y": m.rotation("X", -90)}[axis]
        m.transform(tap, R)
        shift = {"Z": (at[0], at[1], 0.0), "X": (0.0, at[0], at[1]), "Y": (at[0], 0.0, at[1])}[axis]
        m.transform(tap, m.translation(*shift))
    cuts = [tap]
    r = f.major / 2 + f.thread_clearance
    if mouths[0]:
        cuts.append(m.frustum(r + 1.0, r - 1.5, a0 - 1.0, a0 + 1.5, axis, at))
    if mouths[1]:
        cuts.append(m.frustum(r - 1.5, r + 1.0, a1 - 1.5, a1 + 1.0, axis, at))
    return cuts


# ------------------------------------------------------------------ camera holder
def holder(p: Mount, name="camera_holder"):
    """The camera cradle. The PCB slides down from the top between the side walls, rests on
    the floor ledge and lies between the four standoffs behind it and the two front ribs;
    pcb_keeper closes the top. No screws touch the PCB."""
    f = p.fasteners
    wi, wo, h = p.wall_inner_x, p.wall_outer_x, p.holder_height / 2
    zb, zf = p.rear_plate_back_z, p.rear_plate_front_z
    adds = [m.box(-wo, wo, -h, h, zb, zf)]
    cuts = [m.box(-p.rear_window / 2, p.rear_window / 2, -p.rear_window / 2, p.rear_window / 2, zb - 1, zf + 1)]
    rib_reach, rib_t = p.front_rib
    rib_z0 = p.pcb_front_z + p.pcb_slot_clearance
    for sx in (-1, 1):
        x0, x1 = sorted((sx * wi, sx * wo))
        adds.append(m.box(x0, x1, -h, h, zb, 0.0))
        adds.append(m.cylinder(p.holder_front_radius, x0, x1, "X", (0.0, 0.0)))
        # Front rib: keeps the PCB's side edge against the standoffs.
        r0, r1 = sorted((sx * (wi - rib_reach), sx * (wi + 0.01)))
        adds.append(m.box(r0, r1, -h, h, rib_z0, rib_z0 + rib_t))
        # Pitch index fin: front face on the plane through the pitch axis, 45-degree underside.
        f0, f1, reach = p.index_fin
        fin = [(sx * wo, 0.0), (sx * (wo + reach), 0.0), (sx * (wo + reach), -1.0), (sx * wo, -1.0 - reach)]
        adds.append(m.extrude(fin if sx > 0 else fin[::-1], f0, f1, "Y"))
        # Printed nut pocket on the inner face, flat side up when printing; the nut goes in
        # from inside before the PCB.
        n0, n1 = sorted((sx * (wi - 0.01), sx * (wi + p.pitch_nut_depth)))
        cuts.append(m.extrude(m.hexagon(f.nut_pocket_af, vertex_dir=0.0), n0, n1, "X"))
        # Hole for the keeper's peg, down into the wall top (a teardrop: it prints horizontal).
        pd, ph, pdepth = p.keeper_peg
        cuts.append(m.extrude(m.teardrop(ph / 2, tip_dir=math.pi / 2), h - pdepth, h + 1, "Y",
                              (sx * (wi + p.holder_wall / 2), p.keeper_z)))
    cuts.append(m.extrude(m.teardrop(f.shank_clearance / 2, tip_dir=math.pi / 2), -wo - 1, wo + 1, "X"))
    # Floor ledge under the PCB's bottom edge, from the rear plate to the front rib plane.
    adds.append(m.box(-wi + 0.01, wi - 0.01, -h, -p.pcb_half - 0.05, zf - 0.01, rib_z0 + rib_t))
    hp = p.camera.hole_pitch_outer.value / 2
    for x in (-hp, hp):
        for y in (-hp, hp):
            adds.append(m.cylinder(p.standoff_diameter / 2, zf - 0.01, p.pcb_back_z, "Z", (x, y)))
    # 45-degree chamfers on the rear vertical edges: the swept corner is what limits how
    # close the two cameras can stand when both turn outward.
    cuts += _rear_chamfers(p, -h - 1, h + 1)
    # Cable-tie slot pairs below and above the window, for a tie, string or the cable
    # itself woven through.
    sl, sw = p.tie_slot
    ym = (p.rear_window / 2 + h) / 2
    for y in (-ym, ym):
        for x in (-6.0, 6.0):
            cuts.append(m.box(x - sl / 2, x + sl / 2, y - sw / 2, y + sw / 2, zb - 1, zf + 1))
    return m.solid(name, adds, cuts)


def _rear_chamfers(p: Mount, y0, y1):
    """45-degree cuts off the holder's rear vertical edges, from y0 to y1."""
    wo, zb, c = p.wall_outer_x, p.rear_plate_back_z, p.holder_rear_chamfer
    cuts = []
    for sx in (-1, 1):
        # exactly 45 degrees, from (wo - c, zb) to (wo, zb + c)
        tri = [(sx * (wo + 10), zb - 1), (sx * (wo - c - 1), zb - 1), (sx * (wo + 10), zb + c + 10)]
        cuts.append(m.extrude(tri if sx < 0 else tri[::-1], y0, y1, "Y"))
    return cuts


def pcb_keeper(p: Mount, name="pcb_keeper"):
    """Bar across the holder's wall tops, pegged into them, with a tongue down onto the
    PCB's top edge. Local frame: the holder's."""
    wi, wo, h = p.wall_inner_x, p.wall_outer_x, p.holder_height / 2
    t = p.keeper_thickness
    zc = p.keeper_z
    half = p.keeper_peg[0] / 2 + 1.5  # around the pegs
    xe = wi + p.holder_wall / 2 + half  # just past the pegs
    adds = [m.box(-xe, xe, h, h + t, zc - half, zc + half)]
    # Tongue between the front ribs, 0.2 above the PCB edge, narrower than the PCB slot.
    tz = (p.pcb_front_z - p.pcb_back_z) / 2 - 0.2
    adds.append(m.box(-(wi - p.front_rib[0] - 0.3), wi - p.front_rib[0] - 0.3, p.pcb_half + 0.2, h + 0.01,
                      zc - tz, zc + tz))
    pd, ph, pdepth = p.keeper_peg
    for sx in (-1, 1):
        adds.append(m.cylinder(pd / 2, h - pdepth + 0.5, h + 0.01, "Y", (sx * (wi + p.holder_wall / 2), zc),
                               segments=24))
    return m.solid(name, adds, _rear_chamfers(p, h - pdepth - 1, h + t + 1))


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
    cuts = [m.extrude(m.teardrop(f.shank_clearance / 2, tip_dir=0.0), ai - 1, ao + 1, "X")]  # tip toward +Y
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
    # The yaw screw threads into the base; cut after mirroring so both sides stay right-handed.
    return m.solid(ob.name, [ob], threaded_hole(p, yb, yt, "Y"))


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
def _carriage_outline(p: Mount, arc_deg=40.0, chamfer=3.0):
    """Full width over the rail, where the lock bolts sit; in front of the yaw axis only an
    arc that carries the yaw scale, tapering back to the full width at the axis."""
    half, zb, r = p.carriage_width / 2, p.carriage_back_z, p.carriage_front
    pts = [(-half + chamfer, zb), (half - chamfer, zb), (half, zb + chamfer), (half, 0.0)]
    n = 16
    for i in range(n + 1):
        a = math.radians(arc_deg - 2 * arc_deg * i / n)  # from +X side to -X side
        pts.append((r * math.sin(a), r * math.cos(a)))
    pts += [(-half, 0.0), (-half, zb + chamfer)]
    return pts


def carriage(p: Mount, side="right"):
    f = p.fasteners
    sign = 1 if side == "right" else -1
    y0, y1 = p.rail_top_y, p.yoke_bottom_y
    half = p.carriage_width / 2
    zb, zf = p.carriage_back_z, p.carriage_front
    plate = m.extrude(_carriage_outline(p), y0, y1, "Y")
    kw = p.slot_width / 2 - p.printing.sliding_clearance
    key = m.box(-half + 2, half - 2, y0 - p.key_height, y0 + 0.01, p.rail_axis_z - kw, p.rail_axis_z + kw)
    cuts = [m.cylinder(f.shank_clearance / 2, y0 - 5, y1 + 1, "Y", (x, p.rail_axis_z), segments=48)
            for x in (-p.lock_bolt_offset, p.lock_bolt_offset)]
    cuts.append(m.cylinder(f.shank_clearance / 2, y0 - 1, y1 + 1, "Y", (0.0, 0.0), segments=48))
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


# ------------------------------------------------------------------ rail
def _rail_channels(p: Mount, x0, x1, slot_end):
    """Cuts shared by the rail and its coupon: top slot, nut tunnel, key groove underneath."""
    zr = p.rail_axis_z
    yb, yt = p.rail_bottom_y, p.rail_top_y
    kw, kh = p.key_channel
    return [
        m.box(-slot_end, slot_end, yt - p.rail_web - 0.5, yt + 1, zr - p.slot_width / 2, zr + p.slot_width / 2),
        m.box(x0 - 1, x1 + 1, yt - p.rail_web - p.tunnel_height, yt - p.rail_web, zr - p.tunnel_width / 2, zr + p.tunnel_width / 2),
        m.box(x0 - 1, x1 + 1, yb - 1, yb + kh, zr - kw / 2, zr + kw / 2),
    ]


def _rail_floor_thread(p: Mount, x):
    """Threaded hole from the groove ceiling up into the tunnel, for the bracket screw."""
    ceiling = p.rail_bottom_y + p.key_channel[1]
    return threaded_hole(p, ceiling, ceiling + p.rail_floor_thread, "Y", (x, p.rail_axis_z), mouths=(True, False))


def rail(p: Mount, name="rail"):
    L = p.rail_length / 2
    zr, d = p.rail_axis_z, p.rail_depth / 2
    yb, yt = p.rail_bottom_y, p.rail_top_y
    adds = [m.box(-L, L, yb, yt, zr - d, zr + d)]
    cuts = _rail_channels(p, -L, L, L - 3.0)
    for sx in (-1, 1):
        cuts += _rail_floor_thread(p, sx * p.bracket_centre_x)
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
    label = m.text("SIGHT v0.1", 4.0, 1.2, name="label")
    m.transform(label, m.translation(0.0, yb + 10.0, zr + d - 0.6))  # on the front face, under the cameras
    cuts.append(label)
    return m.solid(name, adds, cuts)


# ------------------------------------------------------------------ brackets
def _saddle(p: Mount, z0, z1):
    """The block under a rail end: keyed into the rail groove, screwed from below.

    Local frame: rig axes, x = 0 at the bracket centre (the rail's threaded hole).
    """
    f = p.fasteners
    w = p.bracket_width / 2
    ys, yb = p.surface_y, p.rail_bottom_y
    zr = p.rail_axis_z
    kw, kh = p.key_channel
    c = p.key_clearance
    h = kh - c
    boss = [(yb - 0.01, zr - kw / 2 + c), (yb - 0.01, zr + kw / 2 - c), (yb + h, zr + kw / 2 - c - h), (yb + h, zr - kw / 2 + c)]
    # The boss's +Z face is a 45-degree slope so the monitor clamp prints it lying on its front.
    adds = [m.box(-w, w, ys, yb, z0, z1), m.extrude(boss, -w / 2, w / 2, "X")]
    # Teardrops toward -Z: the hole and the head recess are horizontal when the monitor
    # clamp prints on its front.
    rd, rdepth = p.saddle_head_recess
    cuts = [m.extrude(m.teardrop(f.shank_clearance / 2, tip_dir=-math.pi / 2), ys - 1, yb + kh + 1, "Y", (0.0, zr)),
            m.extrude(m.teardrop(rd / 2, tip_dir=-math.pi / 2), ys - 1, ys + rdepth, "Y", (0.0, zr))]
    # Cable-tie slot pair on the strip behind the rail, for a cable running back along Z.
    sl, sw = p.tie_slot
    zt = (z0 + zr - p.rail_depth / 2) / 2
    for x in (-6.0, 6.0):
        cuts.append(m.box(x - sw / 2, x + sw / 2, ys - 1, yb + 1, zt - sl / 2, zt + sl / 2))
    return adds, cuts


def desk_foot(p: Mount, name="desk_foot"):
    """Stands the rail on a desk; the pad reaches forward under the cameras and back."""
    w = p.bracket_width / 2
    adds, cuts = _saddle(p, *p.saddle_z)
    fz0, fz1 = p.foot_z
    outline = [(x, z + (fz0 + fz1) / 2) for x, z in m.rounded_rect(p.bracket_width, fz1 - fz0, 6.0)]
    adds.append(m.extrude(outline, p.surface_y, p.surface_y + p.foot_thickness, "Y"))
    return m.solid(name, adds, cuts)


def monitor_clamp(p: Mount, side="right"):
    """Hangs the rail on the monitor's top edge: the saddle rests on the top, a lip hooks
    over the front bezel, and a sliding rear arm (clamp_arm) closes on the back.

    The arm bolts to an ear beyond the rail end that rises to the rail top, so the arm's
    knob sits above the monitor. Built for the right end (ear at +X), mirrored for the left.
    """
    f = p.fasteners
    w = p.bracket_width / 2
    ys = p.surface_y
    lip0 = p.monitor_front_z + p.felt_thickness
    lip1 = lip0 + p.lip_thickness
    adds, cuts = _saddle(p, p.saddle_z[0], lip1)
    adds.append(m.box(-w, w + p.clamp_ear, ys - p.felt_thickness - p.lip_drop, ys + 0.01, lip0, lip1))
    # The ear's lower part joins the saddle; its upper part stands 0.2 off the rail end and
    # 1 mm below the rail top, so a carriage at the end of the rail passes over it.
    adds.append(m.box(w - 0.01, w + p.clamp_ear, ys, p.rail_bottom_y + 0.01, p.saddle_z[0], lip1))
    adds.append(m.box(w + 0.2, w + p.clamp_ear, p.rail_bottom_y, p.rail_top_y - 1.0, p.saddle_z[0], lip1))
    yb, zb = p.clamp_bolt_y, p.clamp_bolt_z
    cuts.append(m.extrude(m.teardrop(f.shank_clearance / 2, tip_dir=-math.pi / 2), w - 1, w + p.clamp_ear + 1, "X", (yb, zb)))
    # Drop-in slot for the printed nut, open at the top, corners up and down.
    x1 = w + p.clamp_ear - p.clamp_nut_inset
    corners = f.nut_pocket_af / math.cos(math.radians(30))
    cuts.append(m.box(x1 - f.nut_thickness - 0.4, x1, yb - corners / 2 - 0.1, p.rail_top_y,
                      zb - f.nut_pocket_af / 2, zb + f.nut_pocket_af / 2))
    ob = m.solid(_side("monitor_clamp", side), adds, cuts)
    if side == "left":
        _mirror_x(ob)
    return ob


def clamp_arm(p: Mount, name="clamp_arm"):
    """Rear jaw of the monitor clamp. Local frame: plate from x = 0 to arm_plate, the leg's
    inner (monitor-side) face at z = 0, the bar's underside on the monitor-top plane."""
    f = p.fasteners
    t = p.arm_plate
    ys = p.surface_y
    top = ys + p.arm_bar_height
    leg = 10.0  # along Z: the leg is the part that bends when the clamp is tightened
    yb = p.clamp_bolt_y
    adds = [
        m.box(0.0, t, ys, top, -leg, p.arm_bar_front),
        m.box(0.0, t, ys - p.felt_thickness - p.arm_leg_drop, top, -leg, 0.0),
    ]
    s0, s1 = p.arm_slot
    r = f.shank_clearance / 2 + 0.05
    cuts = [m.box(-1, t + 1, yb - r, yb + r, s0, s1),
            m.cylinder(r, -1, t + 1, "X", (yb, s0)), m.cylinder(r, -1, t + 1, "X", (yb, s1))]
    # Monitor-depth scale on the bar's outer top edge, read against the front face of the
    # clamp's lip (the knob hides the bolt itself): a tick every 10 mm, long every 20 mm.
    e = p.printing.engrave_depth
    d0, d1 = p.monitor_depth_range
    lip_front = p.monitor_front_z + p.felt_thickness + p.lip_thickness
    for depth in range(int(math.ceil(d0 / 10.0)) * 10, int(d1) + 1, 10):
        z = s0 + (depth - d0) + (lip_front - p.clamp_bolt_z)
        cuts.append(m.box(t - e, t + 1, top - (4.0 if depth % 20 == 0 else 2.5), top + 1, z - 0.3, z + 0.3))
    return m.solid(name, adds, cuts)


# ------------------------------------------------------------------ printed fasteners
def _lobed(r, lobes, depth=1.4, n=192):
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r - depth * (0.5 - 0.5 * math.cos(lobes * a))
        out.append((rr * math.cos(a), rr * math.sin(a)))
    return out


SCREWS = ("rail_lock", "yaw", "pitch", "bracket", "clamp")  # one printed screw per joint type


def screw(p: Mount, joint, proxy=False):
    """Printed screw for one joint type: a lobed knob as the head (a knurled disk with a
    coin slot for the bracket screw, which sits in a recess) and a threaded shank whose
    length comes from fastener_stacks. Prints head down.

    proxy=True gives the same head on a plain shank at the thread's minor diameter, for
    the collision checks: a real thread would clash with its mating thread wherever the
    two helices are not phased exactly as printed.
    """
    from .params import fastener_stacks
    f = p.fasteners
    length = fastener_stacks(p)[joint]["length"]
    if joint == "bracket":
        hd, hh = p.bracket_head
        head = m.extrude(_lobed(hd / 2, 12, 0.8), -hh, 0.01, "Z")
        cuts = [m.box(-hd, hd, -0.8, 0.8, -hh - 1, -hh + 2.0)]
    else:
        head = m.extrude(_lobed(p.knob_diameter / 2, p.knob_lobes), -p.knob_height, 0.01, "Z")
        cuts = []
    if proxy:
        shank = m.cylinder(f.minor / 2 - 0.05, 0.0, length, "Z", segments=32)
    else:
        shank = m.thread(z0=0.0, z1=length, chamfer=(False, True), name="shank", **f.rod())
    return m.solid(f"screw_{joint}" + ("_proxy" if proxy else ""), [head, shank], cuts)


def nut(p: Mount, name="nut"):
    """Printed hex nut, one corner toward +Y; prints flat."""
    f = p.fasteners
    body = m.extrude(m.hexagon(f.nut_af, vertex_dir=math.pi / 2), 0.0, f.nut_thickness, "Z")
    return m.solid(name, [body], threaded_hole(p, 0.0, f.nut_thickness))


# ------------------------------------------------------------------ fit coupons
def coupon_pcb(p: Mount, name="coupon_pcb"):
    """The back of the holder: rear plate, standoffs, floor ledge, front ribs and keeper
    holes. The PCB must slide down into it and sit flat, and pcb_keeper must peg on."""
    full = holder(p, name)
    cut = m.box(-100, 100, -100, 100, p.pcb_front_z + p.pcb_slot_clearance + p.front_rib[1] + 2.0, 100)
    return m.solid(name, [full], [cut])


def coupon_thread(p: Mount, name="coupon_thread"):
    """Both thread joints the rig uses, in its print orientation (Z up): a vertical
    threaded hole like the yoke's and the rail's, and a horizontal pass-through with a nut
    pocket like the holder's pitch joint. Try screw_rail_lock in each, with a nut."""
    f = p.fasteners
    adds = [m.box(-16.0, 0.0, -10.0, 10.0, 0.0, p.yoke_base_thickness),
            m.box(0.0, p.holder_wall, -10.0, 10.0, 0.0, 18.0)]
    cuts = threaded_hole(p, 0.0, p.yoke_base_thickness, "Z", (-8.0, 0.0))
    zc = 9.0
    cuts.append(m.extrude(m.teardrop(f.shank_clearance / 2, tip_dir=math.pi / 2), -1.0, p.holder_wall + 1, "X", (0.0, zc)))
    cuts.append(m.extrude(m.hexagon(f.nut_pocket_af, vertex_dir=0.0), -0.01, p.pitch_nut_depth, "X", (0.0, zc)))
    return m.solid(name, adds, cuts)


def coupon_rail(p: Mount, length=30.0, name="coupon_rail"):
    """A slice of the rail profile: slot, nut tunnel, key groove and one threaded bracket hole."""
    zr, d = p.rail_axis_z, p.rail_depth / 2
    L = length / 2
    adds = [m.box(-L, L, p.rail_bottom_y, p.rail_top_y, zr - d, zr + d)]
    cuts = _rail_channels(p, -L, L, L - 3.0) + _rail_floor_thread(p, 0.0)
    return m.solid(name, adds, cuts)


def coupon_slider(p: Mount, length=24.0, name="coupon_slider"):
    """A carriage slice with the key and one lock-screw hole, to try on coupon_rail with
    screw_rail_lock and a nut in the tunnel."""
    zr, d = p.rail_axis_z, p.rail_depth / 2
    y0, y1 = p.rail_top_y, p.yoke_bottom_y
    L = length / 2
    kw = p.slot_width / 2 - p.printing.sliding_clearance
    adds = [m.box(-L, L, y0, y1, zr - d, zr + d),
            m.box(-L + 1, L - 1, y0 - p.key_height, y0 + 0.01, zr - kw, zr + kw)]
    cuts = [m.cylinder(p.fasteners.shank_clearance / 2, y0 - 5, y1 + 1, "Y", (0.0, zr), segments=48)]
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


def monitor_reference(p: Mount, depth, name="ref_monitor"):
    """A stand-in for the monitor's top edge, in the frame of assembly.monitor_matrix:
    front face at z = 0, top at y = 0, `depth` deep where the clamp's arm touches."""
    return m.box(-300.0, 300.0, -350.0, 0.0, -depth, 0.0, name=name)


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
