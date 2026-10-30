"""Ready-to-print build plates: every part of a set, arranged on the printer's bed.

Pure Python and numpy (no bpy), so the packing is testable on its own. Each part keeps
its print orientation; it may only turn 90 degrees about the bed normal.
"""

import io
import zipfile

import numpy as np

# One plate each, printed in this order: the fit coupons with a knob first, then the
# monitor rig split by where its knobs go, so a failed plate reprints only its own group.
# The rig plates together hold every rig part in its outputs.PRINTS quantity. Desk feet
# are an option and stay single files.
PLATE_SETS = {
    "1-coupons": {"coupon_pcb": 1, "coupon_rail": 1, "coupon_slider": 1, "knob": 1},
    # brackets and rail; knobs for the two clamp arms and the two bracket bolts
    "2-base": {"rail": 1, "monitor_clamp_left": 1, "monitor_clamp_right": 1, "clamp_arm": 2, "knob": 4},
    # camera stacks; knobs for the rail locks, yaw and pitch joints
    "3-cameras": {"carriage_left": 1, "carriage_right": 1, "yoke_left": 1, "yoke_right": 1,
                  "camera_holder": 2, "knob": 6},
}


def pack(sizes, bed, margin, gap):
    """Shelf-pack rectangles onto as few plates as needed.

    sizes: [(name, w, d)] footprints. bed: (W, D). Returns [[(name, x, y, rotated)]] with
    (x, y) each footprint's centre, the bed's front-left corner at the origin.
    """
    W, D = bed[0] - 2 * margin, bed[1] - 2 * margin
    items = []
    for name, w, d in sizes:
        if w < d:  # lay the long side along X, so shelves stay shallow
            w, d, rot = d, w, True
        else:
            rot = False
        if w > W or d > D:
            raise ValueError(f"{name} ({w:.0f} x {d:.0f} mm) does not fit the bed")
        items.append((name, w, d, rot))
    items.sort(key=lambda it: (-it[2], -it[1]))
    plates = []  # each: list of shelves [y0, depth, x_used, placements]
    for name, w, d, rot in items:
        placed = False
        for shelves in plates:
            for shelf in shelves:
                if d <= shelf[1] and shelf[2] + w <= W:
                    shelf[3].append((name, shelf[2] + w / 2, shelf[0] + d / 2, rot))
                    shelf[2] += w + gap
                    placed = True
                    break
            if placed:
                break
            top = shelves[-1][0] + shelves[-1][1] + gap
            if top + d <= D:
                shelves.append([top, d, w + gap, [(name, w / 2, top + d / 2, rot)]])
                placed = True
                break
        if not placed:
            plates.append([[0.0, d, w + gap, [(name, w / 2, d / 2, rot)]]])
    return [[(n, x + margin, y + margin, r) for s in shelves for (n, x, y, r) in s[3]] for shelves in plates]


def _rot_z90(v):
    return np.column_stack((-v[:, 1], v[:, 0], v[:, 2]))


def place(verts, x, y, rotated):
    """Move a part's print-oriented vertices so its footprint is centred at (x, y)."""
    v = _rot_z90(verts) if rotated else verts.copy()
    lo, hi = v.min(axis=0), v.max(axis=0)
    return v + np.array([x - (lo[0] + hi[0]) / 2, y - (lo[1] + hi[1]) / 2, -lo[2]])


def write_3mf(path, objects):
    """3MF with one object per part, so the slicer keeps them separate. objects: [(name, verts, tris)]."""
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
              'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n<resources>\n')
    for i, (name, v, t) in enumerate(objects, 1):
        out.write(f'<object id="{i}" name="{name}" type="model"><mesh><vertices>\n')
        out.writelines(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>\n' for a, b, c in v)
        out.write('</vertices><triangles>\n')
        out.writelines(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>\n' for a, b, c in t)
        out.write('</triangles></mesh></object>\n')
    out.write('</resources>\n<build>\n')
    out.writelines(f'<item objectid="{i}"/>\n' for i in range(1, len(objects) + 1))
    out.write('</build>\n</model>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
                   'openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType='
                   '"application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.'
                   'org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", out.getvalue())
