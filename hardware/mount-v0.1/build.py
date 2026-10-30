"""Generate LYNX SIGHT camera mount v0.1: parts, checks, STLs, .blend and renders.

    uv run build.py                 # everything (renders take a few minutes on CPU)
    uv run build.py --no-render     # parts, checks, STLs and .blend only
    blender -b --python build.py -- --no-render   # the same inside a Blender 5.x install

Outputs go next to this file: stl/, plates/, blend/, renders/, validation/. The build exits
non-zero when a check fails.
"""

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bpy  # noqa: E402

from lynx_mount import assembly as asm, outputs, parts, plates, validate  # noqa: E402
from lynx_mount.params import DEFAULT, Mount  # noqa: E402

# On the monitor's top edge, turned slightly in and looking down at the user.
DISPLAY_POSE = asm.Pose(100.0, asm.Setting(8.0, -15.0), asm.Setting(8.0, -15.0), stand="monitor", monitor_depth=30.0)


def build_parts(p: Mount):
    built = {
        "rail": parts.rail(p),
        "monitor_clamp_left": parts.monitor_clamp(p, "left"),
        "monitor_clamp_right": parts.monitor_clamp(p, "right"),
        "clamp_arm": parts.clamp_arm(p),
        "desk_foot": parts.desk_foot(p),
        "carriage_left": parts.carriage(p, "left"),
        "carriage_right": parts.carriage(p, "right"),
        "yoke_left": parts.yoke(p, "left"),
        "yoke_right": parts.yoke(p, "right"),
        "camera_holder": parts.holder(p),
        "knob": parts.knob(p),
        "coupon_pcb": parts.coupon_pcb(p),
        "coupon_rail": parts.coupon_rail(p),
        "coupon_slider": parts.coupon_slider(p),
    }
    return built


def write_plates(p: Mount, meshes):
    """Each plate set nested on the bed as a .3mf file, one object per part."""
    pr = p.printing
    plate_dir = os.path.join(HERE, "plates")
    os.makedirs(plate_dir, exist_ok=True)
    for old in os.listdir(plate_dir):
        os.remove(os.path.join(plate_dir, old))
    out = {}
    for set_name, keys in plates.PLATE_SETS.items():
        items = [(f"{key}_{i + 1}" if qty > 1 else key, *meshes[key]) for key, qty in keys.items() for i in range(qty)]
        by_name = {name: (vs, tris) for name, vs, tris in items}
        layout = plates.pack(items, pr.bed_xyz[:2], pr.bed_margin, pr.plate_gap)
        for n, placed in enumerate(layout, 1):
            objects = []
            for name, turns, corner in placed:
                vs, tris = by_name[name]
                objects.append((name, plates.place(vs, turns, corner), tris))
            allv = np.vstack([v for _, v, _ in objects])
            lo, hi = allv.min(axis=0), allv.max(axis=0)
            m = pr.bed_margin - 1e-6
            fits = bool((lo[:2] >= m).all() and (hi[:2] <= np.array(pr.bed_xyz[:2]) - m).all()
                        and hi[2] <= pr.bed_xyz[2] and apart(objects, pr.plate_gap))
            fname = f"{set_name}.3mf" if len(layout) == 1 else f"{set_name}-{n}.3mf"
            plates.write_3mf(os.path.join(plate_dir, fname), objects)
            out[fname] = dict(parts=[o[0] for o in objects], fits_bed=fits,
                              extent_mm=[round(float(v), 1) for v in hi - lo])
    # The rig plates must add up to the full monitor rig.
    rig = {}
    for set_name, keys in plates.PLATE_SETS.items():
        if set_name.endswith("coupons"):
            continue
        for key, qty in keys.items():
            rig[key] = rig.get(key, 0) + qty
    expected = {k: q for k, (_, q, _) in outputs.PRINTS.items() if not k.startswith(("coupon", "desk_foot"))}
    if rig != expected:
        out["rig_complete"] = dict(fits_bed=False, plates=rig, expected=expected)
    return out


def apart(objects, gap):
    """No two parts' footprints, each grown by just under half the gap, share a cell."""
    res = plates.RES
    r = int(gap / 2 / res) - 1
    grid = np.zeros((int(600 / res), int(600 / res)), np.int16)
    for _, vs, tris in objects:
        g = plates.dilate(plates.footprint(vs, tris, res), r)
        i, j = (np.floor(vs[:, :2].min(axis=0) / res).astype(int) - r + int(100 / res))
        grid[i:i + g.shape[0], j:j + g.shape[1]] += g
    return bool(grid.max() <= 1)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-render", action="store_true", help="skip the Cycles previews")
    ap.add_argument("--samples", type=int, default=48)
    args = ap.parse_args(argv)
    p = DEFAULT
    t0 = time.time()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version = 0  # no .blend1 backups next to the tracked file
    built = build_parts(p)
    refs = {k: v for k, v in parts.camera_reference(p).items()}
    fov = parts.fov_frustum(p)
    monitors = {d: parts.monitor_reference(p, d, name=f"ref_monitor_{d:g}")
                for stand, d in validate.stand_configs(p) if stand == "monitor"}
    display_monitor = parts.monitor_reference(p, DISPLAY_POSE.monitor_depth)

    report = {"generator": "hardware/mount-v0.1/build.py", "blender": bpy.app.version_string, "parts": {}}
    stl_dir = os.path.join(HERE, "stl")
    os.makedirs(stl_dir, exist_ok=True)
    meshes = {}
    for key, (rot, qty, why) in outputs.PRINTS.items():
        ob = built[key]
        health = validate.mesh_health(ob)
        M = outputs.print_matrix(ob, rot)
        meshes[key] = outputs.print_mesh(ob, M)
        outputs.write_stl(os.path.join(stl_dir, f"{key}.stl"), *meshes[key])
        # Analyse the exported orientation itself.
        probe = bpy.data.objects.new("probe", ob.data.copy())
        probe.data.transform(M)
        probe.data.update()
        pr = validate.print_report(probe, p.printing.bed_xyz, p.printing.bed_margin,
                                  p.printing.max_overhang_deg)
        bpy.data.meshes.remove(probe.data)
        report["parts"][key] = dict(quantity=qty, orientation=why, stl=f"stl/{key}.stl", mesh=health, print=pr)

    report["plates"] = write_plates(p, meshes)
    report["fasteners"] = validate.check_fasteners(p)
    report["ranges"] = validate.check_ranges(p)
    report["assembly"] = validate.check_assembly(p, built, refs, fov, monitors)

    failures = [f"mesh:{k}" for k, v in report["parts"].items() if not v["mesh"]["ok"]]
    failures += [f"bed:{k}" for k, v in report["parts"].items() if not v["print"]["fits_bed"]]
    failures += [f"plate:{k}" for k, v in report["plates"].items() if not v["fits_bed"]]
    failures += [k for k in ("fasteners", "ranges") if not report[k]["ok"]]
    failures += [f"assembly.{k}" for k in ("fit", "motion") if not report["assembly"][k]["ok"]]
    report["ok"] = not failures
    report["failures"] = failures

    val_dir = os.path.join(HERE, "validation")
    os.makedirs(val_dir, exist_ok=True)
    with open(os.path.join(val_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    for ob in monitors.values():
        bpy.data.meshes.remove(ob.data)
    cols = outputs.build_scene(p, built, refs, fov, display_monitor, DISPLAY_POSE)
    blend_dir = os.path.join(HERE, "blend")
    os.makedirs(blend_dir, exist_ok=True)
    if "_csg_scratch" in bpy.data.collections:
        bpy.data.collections.remove(bpy.data.collections["_csg_scratch"])
    if not args.no_render:
        render_dir = os.path.join(HERE, "renders")
        os.makedirs(render_dir, exist_ok=True)
        outputs.render_views(os.path.join(render_dir, ""), cols, p.surface_y, samples=args.samples)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(blend_dir, "mount-v0.1.blend"), compress=True)

    print(f"build {'OK' if report['ok'] else 'FAILED'} in {time.time() - t0:.1f}s; failures: {failures or 'none'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    sys.exit(main(argv))
