# Camera mount v0.1 — generator

This is the parametric Blender source for the stereo camera mount. The design, BOM,
print settings, assembly and test plan are in
[docs/hardware/mount-v0.1.md](../../docs/hardware/mount-v0.1.md), and the camera
dimensions in [docs/hardware/camera-b0332.md](../../docs/hardware/camera-b0332.md).

## Build

You need Ubuntu (x86-64) and [uv](https://docs.astral.sh/uv/). The `bpy` module is
Blender 5.2.3 LTS, about 400 MB.

```bash
cd hardware/mount-v0.1
uv run build.py --no-render      # parts, checks, STLs and .blend (~15 s)
uv run build.py                  # also the Cycles previews (~2-3 min on CPU)
uv run python -m unittest discover -s tests
```

With a Blender 5.x install instead: `blender -b --python build.py -- --no-render`.
The build exits non-zero if a check fails.

## Layout

| Path | Contents |
|---|---|
| `lynx_mount/params.py` | Every dimension, in mm and degrees. Each camera dimension is tagged with its source (MFR or ASSUMED), and fit clearances are marked FIT |
| `lynx_mount/parts.py` | One function per printable part, each built in its own local frame |
| `lynx_mount/assembly.py` | Rig-frame poses for a given baseline, per-camera yaw and pitch, stand (monitor clamp or desk feet) and monitor depth, using the shared conventions |
| `lynx_mount/validate.py` | Mesh, print, fit, collision-sweep, access and fastener checks |
| `lynx_mount/outputs.py` | Print orientations, STL writer, the `.blend` scene and the renders |
| `lynx_mount/plates.py` | Which parts go on which ready-made print plate, how they are arranged, and the .3mf writer |
| `lynx_mount/mesh.py` | Solid primitives and exact booleans |
| `stl/` | The printable parts, generated and lying in print orientation |
| `plates/` | Ready-to-print P2S plates (`1-coupons`, `2-base`, `3-cameras`) as .3mf files |
| `blend/mount-v0.1.blend` | Collections: Assembly (on the monitor), Monitor, Camera reference, Keep-outs and FOV, Desk variant, Exploded, Print layout |
| `renders/` | Previews |
| `validation/report.json` | Results of the last build's checks |

To change a dimension, edit `params.py`, rebuild and commit the regenerated outputs
together with the change. The `.blend` file is an output: edits made in Blender are
overwritten by the next build.
