"""Ready-to-print build plates: every part of a set, nested on the printer's bed.

Pure Python and numpy (no bpy), so the packing is testable on its own. Parts are nested
by their real footprints, not bounding boxes, so small parts fill the corners of L-shaped
ones. Each part keeps its print orientation; it may only turn by quarter turns about the
bed normal.
"""

import io
import math
import zipfile

import numpy as np

# Printed in this order: the fit coupons with a knob first, then the whole monitor rig.
# The rig plate holds every rig part in its outputs.PRINTS quantity (the build checks it).
# Desk feet are an option and stay single files.
PLATE_SETS = {
    "1-coupons": {"coupon_pcb": 1, "coupon_rail": 1, "coupon_slider": 1, "knob": 1},
    "2-mount": {"rail": 1, "monitor_clamp_left": 1, "monitor_clamp_right": 1, "clamp_arm": 2,
                "carriage_left": 1, "carriage_right": 1, "yoke_left": 1, "yoke_right": 1,
                "camera_holder": 2, "knob": 10},
}


RES = 0.5  # mm per footprint cell


def _rotz(verts, quarter_turns):
    v = verts.copy()
    for _ in range(quarter_turns % 4):
        v = np.column_stack((-v[:, 1], v[:, 0], v[:, 2]))
    return v


def footprint(verts, tris, res=RES):
    """Boolean grid of the cells a part covers on the bed, from its triangles' shadows.

    Cell (i, j) covers x in [i*res, (i+1)*res) above the part's min x and min y, and counts
    as covered when any triangle's projection touches it.
    """
    xy = verts[:, :2] - verts[:, :2].min(axis=0)
    nx, ny = (np.ceil(xy.max(axis=0) / res).astype(int) + 1)
    grid = np.zeros((nx, ny), bool)
    for t in tris:
        a, b, c = xy[t[0]], xy[t[1]], xy[t[2]]
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-9:
            continue
        i0, j0 = np.floor(np.minimum(np.minimum(a, b), c) / res).astype(int)
        i1, j1 = np.floor(np.maximum(np.maximum(a, b), c) / res).astype(int)
        ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
        # Test each cell's centre, and also mark the vertices' own cells so thin
        # triangles are never lost between centres.
        px, py = (ii + 0.5) * res, (jj + 0.5) * res
        w0 = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
        w1 = (c[0] - b[0]) * (py - b[1]) - (c[1] - b[1]) * (px - b[0])
        w2 = (a[0] - c[0]) * (py - c[1]) - (a[1] - c[1]) * (px - c[0])
        s = np.sign(area)
        inside = (s * w0 >= 0) & (s * w1 >= 0) & (s * w2 >= 0)
        grid[ii[inside], jj[inside]] = True
        for v in (a, b, c):
            grid[min(int(v[0] / res), nx - 1), min(int(v[1] / res), ny - 1)] = True
    return grid


def dilate(grid, r):
    """Grow a footprint by r cells in every direction (a disk), enlarging the grid by r."""
    nx, ny = grid.shape
    out = np.zeros((nx + 2 * r, ny + 2 * r), bool)
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out[r + dx:r + dx + nx, r + dy:r + dy + ny] |= grid
    return out


def _overlaps(occupied, kernel):
    """For every offset (i, j), how many cells kernel shares with occupied[i:, j:]."""
    sx, sy = occupied.shape[0] + kernel.shape[0], occupied.shape[1] + kernel.shape[1]
    f = np.fft.rfft2(occupied.astype(float), (sx, sy)) * np.conj(np.fft.rfft2(kernel.astype(float), (sx, sy)))
    return np.fft.irfft2(f, (sx, sy))[:occupied.shape[0], :occupied.shape[1]]


def pack(parts, bed, margin, gap, res=RES):
    """Nest part footprints onto as few plates as needed.

    parts: [(name, verts, tris)] in print orientation. Each part may turn by quarter turns
    about the bed normal. Every part keeps `gap` from the others and `margin` from the bed
    edge. Returns [[(name, quarter_turns, (x, y) of the footprint's min corner)]].
    """
    r = int(math.ceil(gap / res)) + 1  # +1 cell for the rasterisation error on both parts
    W, D = int((bed[0] - 2 * margin) / res), int((bed[1] - 2 * margin) / res)
    shapes = []
    for name, verts, tris in parts:
        rots = [footprint(_rotz(verts, k), tris, res) for k in range(4)]
        shapes.append((name, rots))
    shapes.sort(key=lambda s: -s[1][0].sum())
    plates = []  # [occupied grid, placements]
    for name, rots in shapes:
        best = None
        for pi, plate in enumerate(plates + [None]):
            occ = plate[0] if plate is not None else np.zeros((W, D), bool)
            for k, g in enumerate(rots):
                if g.shape[0] > W or g.shape[1] > D:
                    continue
                kern = dilate(g, r)
                # Position (i, j) puts g's corner at (i, j); its dilated kernel starts r earlier.
                padded = np.zeros((W + 2 * r, D + 2 * r), bool)
                padded[r:r + W, r:r + D] = occ
                hits = _overlaps(padded, kern)[:W - g.shape[0] + 1, :D - g.shape[1] + 1]
                free = np.argwhere(hits < 0.5)
                if not len(free):
                    continue
                # Bottom-left: lowest top edge first, then leftmost.
                score = (free[:, 1] + g.shape[1]) * 10000 + free[:, 0]
                i, j = free[np.argmin(score)]
                key = (pi, score.min())
                if best is None or key < best[0]:
                    best = (key, pi, k, int(i), int(j), g)
            if best is not None and best[1] == pi:
                break  # placed on an existing plate; don't open a new one
        if best is None:
            raise ValueError(f"{name} does not fit the bed")
        _, pi, k, i, j, g = best
        if pi == len(plates):
            plates.append([np.zeros((W, D), bool), []])
        plates[pi][0][i:i + g.shape[0], j:j + g.shape[1]] |= g
        plates[pi][1].append((name, k, (margin + i * res, margin + j * res)))
    return [pl[1] for pl in plates]


def place(verts, quarter_turns, corner):
    """A part's print-oriented vertices turned and moved so its footprint's min corner is at corner."""
    v = _rotz(verts, quarter_turns)
    lo = v.min(axis=0)
    return v + np.array([corner[0] - lo[0], corner[1] - lo[1], -lo[2]])


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
