# OpenVDB Volume Shift/Jitter in Blender: Complete Guide

> Comprehensive research on why reimported smoke/fire VDB sequences drift in Blender, and every known fix — no rebake required.

---

## Table of Contents

1. [The Problem](#the-problem)
2. [Root Cause](#root-cause)
3. [How OpenVDB Transforms Work](#how-openvdb-transforms-work)
4. [Blender Bug History](#blender-bug-history)
5. [Getting openvdb on Windows](#getting-openvdb-on-windows)
6. [Fixes (No Rebake)](#fixes-no-rebake)
   - [Fix 1: Blender Headless Script — Strip Offsets](#fix-1-blender-headless-script--strip-offsets)
   - [Fix 2: Blender Headless Script — Apply Specific Offset](#fix-2-blender-headless-script--apply-specific-offset)
   - [Fix 3: Blender Python — Auto-Bake Corrective Keyframes](#fix-3-blender-python--auto-bake-corrective-keyframes)
   - [Fix 4: Blender Python — Frame-Change Handler](#fix-4-blender-python--frame-change-handler)
   - [Fix 5: Houdini Pass-Through](#fix-5-houdini-pass-through)
   - [Fix 6: Blender Constraints](#fix-6-blender-constraints)
   - [Fix 7: Geometry Nodes (Blender 4.5+)](#fix-7-geometry-nodes-blender-45)
   - [Fix 8: Manual Object Offset](#fix-8-manual-object-offset)
7. [Diagnostic Tools](#diagnostic-tools)
8. [Prevention for Future Simulations](#prevention-for-future-simulations)
9. [Technical Deep Dive: OpenVDB Format](#technical-deep-dive-openvdb-format)
10. [Why Houdini Doesn't Have This Problem](#why-houdini-doesnt-have-this-problem)
11. [Performance Tips for Large VDB Sequences](#performance-tips-for-large-vdb-sequences)
12. [Alternative Formats](#alternative-formats)
13. [References & Sources](#references--sources)

---

## The Problem

You bake a smoke/fire simulation in Blender, export it as OpenVDB, then import the .vdb sequence into another Blender project. The volume appears to shift, slide, scale, or jitter frame-to-frame instead of staying in place. The effect ranges from a subtle wobble to the entire volume drifting across the scene.

This happens because Blender's fluid simulator (Mantaflow) does not write correct spatial positioning data into the VDB files.

---

## Root Cause

**Blender bug [#79711](https://projects.blender.org/blender/blender/issues/79711)** — open since 2020, no active maintainer.

Every OpenVDB file stores a **transform matrix** inside each grid that maps voxel coordinates to world-space positions. This is how any application knows where to place the volume. Mantaflow does NOT write this transform correctly. Specifically:

1. **Mantaflow stores domain position only in its proprietary Unicache (.uni) format**, not in the .vdb files it exports.
2. When **Adaptive Domain** is enabled (the default optimization that shrinks the simulation bounding box to fit the active smoke region), the domain origin and size change every frame.
3. Since the per-frame domain offset is missing from the VDB metadata, the reimported volume appears to move as the adaptive bounds change.

The old pre-Mantaflow smoke system (Blender 2.79b) handled this correctly. The capability was lost when Mantaflow replaced it in Blender 2.82.

**Current status (May 2026):** Mantaflow has no active developer in the Blender project. This bug is classified as a known issue with no planned fix.

---

## How OpenVDB Transforms Work

Each VDB grid contains three things:
- **Tree**: The actual voxel data (sparse hierarchical structure)
- **Transform**: A 4x4 affine matrix mapping index-space to world-space
- **Metadata**: Name, grid class, and custom key-value pairs

The transform matrix looks like this:

```
| voxelSize    0           0           0 |
| 0            voxelSize   0           0 |
| 0            0           voxelSize   0 |
| translateX   translateY  translateZ  1 |
```

- **Voxel size** (diagonal) controls scale — how big each voxel is in world units
- **Translation** (last row) controls position — where the volume sits in world space

When Mantaflow exports VDB, it writes the voxel size correctly but does NOT write the translation. So the volume's position information is lost.

For VDB sequences (one file per frame), each file is fully independent with its own transform. With Adaptive Domain, the translation SHOULD change per frame to track the moving domain bounds. Since Mantaflow omits it, every frame appears at the wrong position.

---

## Blender Bug History

| Bug ID | Description | Status |
|--------|-------------|--------|
| **#79711** | Mantaflow: OpenVDB glitches due to Adaptive Domain | **Open (no maintainer)** |
| T80382 | VDB cache moving around with adaptive domain | Duplicate of #79711 |
| T80884 | Exporting VDB with Adaptive Domain slides origin | Duplicate of #79711 |
| T83990 | VDB adaptive Domain Reimport Position jitter | Duplicate of #79711 |
| T75883 | Adaptive Domain broken for Final bakes with OpenVDB | Open |
| T78705 | VDB Import missing noise cache | Open |
| T55377 | Temperature exported as "Heat" not "Temperature" | Open |
| #156318 | Cycles smoke offset with non-square domains | **Fixed March 2026** |
| #91174 | OpenVDB cache Mantaflow Gas has Hollow Emission | Open |

### Version Timeline

- **Blender 2.79b**: Old smoke system — VDB export worked correctly with adaptive domain
- **Blender 2.82**: Mantaflow replaced old system — VDB offset bug introduced
- **Blender 2.83**: Volume object type added for native VDB import
- **Blender 2.9x**: Bug #79711 reported and confirmed, multiple duplicates filed
- **Blender 3.x**: No fix for adaptive domain VDB offset
- **Blender 4.x**: Fix for non-square domain offset (#156318), but core adaptive domain bug remains
- **Blender 5.0**: 27 new Volume Grid geometry nodes, but Mantaflow bug still unresolved

---

## Getting openvdb on Windows

> **IMPORTANT:** The `pip install pyopenvdb` package on PyPI is **Linux-only** (last updated 2020, Python 3.7 only). It will NOT work on Windows. Here are your actual options:

### Option A: Use Blender's Bundled openvdb (Easiest, Recommended)

Blender 3.6+ ships with the `openvdb` Python module built-in on all platforms, including Windows. You don't need to install anything — it's already there.

**Run scripts via Blender's command line (headless mode):**
```powershell
& "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" -b --python my_vdb_script.py
```

**Or test it interactively in Blender's Python console:**
```python
import openvdb
print(openvdb.LIBRARY_VERSION)
```

The import name is `openvdb` (not `pyopenvdb`). The API is the same — `readAll`, `write`, `createLinearTransform`, etc. all work identically.

**All scripts in this guide use `import openvdb` and are designed to run via Blender on Windows.**

### Option B: conda-forge (Standalone Python)

The conda-forge channel has Windows builds of openvdb:
```powershell
conda create -n vdb python=3.12 -c conda-forge openvdb
conda activate vdb
python -c "import pyopenvdb; print('OK')"
```

Note: Some users report DLL-load failures on Windows. If it works, this gives you a standalone Python environment independent of Blender.

### Option C: WSL2 (Linux on Windows)

If conda-forge fails, use Windows Subsystem for Linux:
```bash
# In WSL2 Ubuntu terminal
pip install pyopenvdb
# or
conda install -c conda-forge openvdb
```

This is the most reliable path to getting the Linux-native pyopenvdb working on a Windows machine.

### Option D: Houdini Apprentice (Free)

SideFX Houdini Apprentice is free and ships with full OpenVDB Python bindings (`hou.VDB`). You get the complete VDB toolset plus a GUI for inspecting and fixing volumes.

---

## Fixes (No Rebake)

### Fix 1: Blender Headless Script — Strip Offsets

**Best for: Volume that jitters/drifts frame-to-frame due to adaptive domain**

This removes all translation from every grid in every frame, keeping only the voxel size. The volume will appear at the world origin.

Save this as `fix_vdb_strip.py`:

```python
import openvdb
import glob
import os

input_dir = r"G:\path\to\your\vdb_sequence"
output_dir = r"G:\path\to\fixed_sequence"
os.makedirs(output_dir, exist_ok=True)

for filepath in sorted(glob.glob(os.path.join(input_dir, "*.vdb"))):
    grids, meta = openvdb.readAll(filepath)
    for grid in grids:
        vs = grid.transform.voxelSize()[0]  # preserve voxel size
        grid.transform = openvdb.createLinearTransform(voxelSize=vs)  # zero translation
    out_path = os.path.join(output_dir, os.path.basename(filepath))
    openvdb.write(out_path, grids=grids, metadata=meta)
    print(f"Fixed: {os.path.basename(filepath)}")

print("Done. All frames corrected.")
```

**How to run on Windows:**
```powershell
& "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" -b --python fix_vdb_strip.py
```

1. Edit `input_dir` and `output_dir` paths in the script
2. Run the command above in PowerShell
3. Import the fixed sequence into Blender
4. Position the Volume object manually to match your scene

**Back up your original VDB files first.**

---

### Fix 2: Blender Headless Script — Apply Specific Offset

**Best for: Volume needs to be at a specific world position**

Save this as `fix_vdb_offset.py`:

```python
import openvdb
import glob
import os

input_dir = r"G:\path\to\your\vdb_sequence"
output_dir = r"G:\path\to\fixed_sequence"
os.makedirs(output_dir, exist_ok=True)

# Set desired world-space position
target_x, target_y, target_z = 2.0, 0.0, -1.5

for filepath in sorted(glob.glob(os.path.join(input_dir, "*.vdb"))):
    grids, meta = openvdb.readAll(filepath)
    for grid in grids:
        vs = grid.transform.voxelSize()[0]
        grid.transform = openvdb.createLinearTransform(matrix=[
            [vs,       0,        0,        0],
            [0,        vs,       0,        0],
            [0,        0,        vs,       0],
            [target_x, target_y, target_z, 1]
        ])
    out_path = os.path.join(output_dir, os.path.basename(filepath))
    openvdb.write(out_path, grids=grids, metadata=meta)

print("Done. All frames repositioned.")
```

**Run:**
```powershell
& "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" -b --python fix_vdb_offset.py
```

---

### Fix 3: Blender Python — Auto-Bake Corrective Keyframes

**Best for: Fixing the jitter inside Blender without modifying VDB files on disk**

This reads each frame's grid transform, computes the difference from frame 1, and inserts corrective location keyframes on the Volume object.

**Run this inside Blender's Scripting workspace (paste and click Run):**

```python
import bpy

# Change this to match your imported volume object name
vol_obj = bpy.data.objects["YourVolumeObject"]
volume = vol_obj.data
scene = bpy.context.scene

# Get reference position from frame 1
scene.frame_set(scene.frame_start)
volume.grids.load()
ref_grid = volume.grids[0]
ref_grid.load()
ref_translation = ref_grid.matrix_object.translation.copy()

print(f"Reference position (frame {scene.frame_start}): {ref_translation}")

# Bake corrective keyframes for every frame
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    volume.grids.load()
    grid = volume.grids[0]
    grid.load()

    current_translation = grid.matrix_object.translation
    delta = ref_translation - current_translation

    vol_obj.location = delta
    vol_obj.keyframe_insert(data_path="location", frame=frame)

    if frame % 50 == 0:
        print(f"  Processed frame {frame}")

print("Done. Corrective keyframes baked on Volume object.")
```

**How to run:**
1. Open Blender with your imported VDB sequence
2. Go to Scripting workspace
3. Paste the script, edit the object name
4. Click Run Script
5. The Volume object now has per-frame location keyframes that cancel out the jitter

---

### Fix 4: Blender Python — Frame-Change Handler

**Best for: Quick runtime fix without baking keyframes**

**Run inside Blender's Scripting workspace:**

```python
import bpy
from bpy.app.handlers import persistent

# Pre-computed offset table (frame: (x, y, z))
# Fill this by analyzing your VDB sequence with the diagnostic script below
OFFSET_TABLE = {
    1: (0.0, 0.0, 0.0),
    2: (-0.1, 0.0, 0.05),
    3: (-0.2, 0.01, 0.1),
    # Add entries for all frames...
}

@persistent
def correct_vdb_offset(scene):
    frame = scene.frame_current
    vol_obj = bpy.data.objects.get("YourVolumeObject")
    if vol_obj is None:
        return
    offset = OFFSET_TABLE.get(frame, (0, 0, 0))
    vol_obj.location = offset

# Register the handler
bpy.app.handlers.frame_change_post.append(correct_vdb_offset)
print("Frame-change handler registered.")
```

---

### Fix 5: Houdini Pass-Through

**Best for: If you have Houdini (even Apprentice, which is free)**

Loading VDB files into Houdini and re-exporting normalizes the grid transforms. Community confirms this eliminates jitter across multiple renderers.

1. Open Houdini
2. Create a **File SOP** node — point to your VDB sequence (use `$F4` frame token in path)
3. Optionally add a **Transform SOP** to recenter if needed
4. Create a **File Cache SOP** — set output to `.vdb` format with a new output path
5. Hit "Save to Disk" to re-export the sequence
6. Import the re-exported files into Blender

---

### Fix 6: Blender Constraints

**Best for: Simple constant offset (not per-frame jitter)**

1. Add an **Empty** at the world position where the volume should be
2. Select your Volume object
3. Add a **Copy Location** constraint (Object Constraint Properties panel)
4. Set Target to the Empty
5. If the VDB already has some correct positioning, enable the **Offset** checkbox

For per-frame varying offsets, keyframe the Empty's position using values from the diagnostic script.

---

### Fix 7: Geometry Nodes (Blender 4.5+)

**Best for: Non-destructive, procedural correction inside the node tree**

1. Select your Volume object
2. Add a **Geometry Nodes** modifier
3. In the node editor:
   - Add an **Import VDB** node (load your sequence)
   - Add a **Transform Geometry** node after it
   - Set the Translation values to correct the offset
   - Drive the values with keyframes or drivers for per-frame correction
4. Connect to Group Output

---

### Fix 8: Manual Object Offset

**Best for: Constant offset across all frames (no per-frame jitter)**

1. Import your VDB sequence
2. Scrub to a frame where the misalignment is clearly visible
3. Select the Volume object
4. In the Properties panel > Object > Transform, adjust the Location values until the volume aligns correctly
5. If the offset is the same on every frame, you're done

---

## Diagnostic Tools

### Inspect VDB Transform Data (via Blender headless)

Save as `inspect_vdb.py` and run via Blender to see what transforms are stored in your VDB files:

```python
import openvdb
import glob
import os

vdb_dir = r"G:\path\to\your\vdb_sequence"

print(f"{'Frame':<30s} | {'Grid':<12s} | {'Voxel Size':<12s} | World Origin (0,0,0)")
print("-" * 85)

for filepath in sorted(glob.glob(os.path.join(vdb_dir, "*.vdb"))):
    filename = os.path.basename(filepath)
    grids = openvdb.readAllGridMetadata(filepath)
    for grid in grids:
        vs = grid.transform.voxelSize()
        origin = grid.transform.indexToWorld((0, 0, 0))
        print(f"{filename:<30s} | {grid.name:<12s} | {vs[0]:<12.6f} | ({origin[0]:.4f}, {origin[1]:.4f}, {origin[2]:.4f})")
```

**Run:**
```powershell
& "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" -b --python inspect_vdb.py
```

If the "World Origin" values change between frames, that's your jitter source.

### Command Line: vdb_print (Linux/Mac/WSL)

```bash
# Full info for one file
vdb_print -l -m smoke_0001.vdb

# Scan all files in a sequence
for f in smoke_*.vdb; do echo "=== $f ==="; vdb_print -l -m "$f"; done
```

### Command Line: vdb_tool (Linux/Mac/WSL)

```bash
# Apply a translation fix to one file
vdb_tool -read input.vdb -transform translate='(-2.5,0,1.3)' -write output.vdb

# Batch process entire sequence
vdb_tool -for n=1,240 -read smoke_{$n:4:pad0}.vdb -transform translate='(0,0,0)' -write fixed_{$n:4:pad0}.vdb -end
```

---

## Prevention for Future Simulations

These settings prevent the issue before it starts:

### 1. Disable Adaptive Domain (Most Important)

This is the single most effective prevention.

- Select your fluid domain object
- Physics Properties > Fluid > Settings
- **Uncheck "Adaptive Domain"**
- Make the domain large enough to contain the entire simulation

Without adaptive domain, the simulation bounding box stays fixed, and the VDB transforms remain consistent across all frames.

### 2. Place Domain at World Origin

- Select the domain object
- Right-click > Set Origin > Origin to 3D Cursor (with cursor at 0,0,0)
- Adjust the domain's size and position **only in Edit Mode**
- The object origin stays at (0,0,0), minimizing transform offset issues

### 3. Use Uni Cache for Internal Work

If you only need the cache within the same Blender project (no cross-project transfer), use the Uni format instead of OpenVDB in the Cache panel. Uni stores the transform data correctly.

### 4. Test a Single Frame First

Before committing to a full sequence render:
- Export one frame as VDB
- Import it into a clean Blender project
- Verify the position is correct
- Only then proceed with the full sequence

### 5. Noise Cache Note

If you used noise upscaling, the noise grids are in a separate `noise/` subfolder with names like `density_noise`. When reimporting:
- Import from the `noise/` folder, not the `data/` folder
- In your shader, use `density_noise` as the attribute name (not `density`)

---

## Technical Deep Dive: OpenVDB Format

### File Structure

1. **Header**: Magic bytes, format version, library version, UUID
2. **Grid Descriptors**: Byte offsets pointing to each grid's data
3. **Per-Grid Data**: Transform + metadata + tree topology + voxel data

### Coordinate Spaces

- **Index Space**: Integer coordinates (i,j,k). The voxel data lives here. Voxel size is always 1.
- **World Space**: Floating-point coordinates (x,y,z) with physical units. Determined by the transform.

Conversion: `world = index * transform_matrix`

### Transform Map Types

| Type | Use Case |
|------|----------|
| UniformScaleMap | Isotropic voxels, no offset |
| UniformScaleTranslateMap | Isotropic voxels + position offset |
| ScaleTranslateMap | Anisotropic voxels + offset |
| AffineMap | Full rotation/shear/scale/translate |
| NonlinearFrustumMap | Camera-aligned perspective volumes |

### What Mantaflow Gets Wrong

Mantaflow writes grids with a `UniformScaleMap` (voxel size only). It should write `UniformScaleTranslateMap` or `ScaleTranslateMap` to include the domain's world-space position. The translation component is simply absent.

### Grid Metadata Fields

Standard metadata stored per-grid:

| Field | Purpose |
|-------|---------|
| Grid Class | "fog_volume", "level_set", "staggered" |
| Grid Name | "density", "flame", "velocity", etc. |
| Save as Half Float | 16-bit quantization flag |
| File BBox Min/Max | Index-space extent of active voxels |

None of these control position — only the Transform does.

---

## Why Houdini Doesn't Have This Problem

| Aspect | Houdini | Blender |
|--------|---------|---------|
| VDB Status | First-class native primitive | External file reference on Volume object |
| Transform Model | Single: grid's internal affine map contains everything | Dual: grid transform + object transform must compose |
| SOP Transforms | Baked directly into the grid's map | Applied at object level, separate from grid data |
| Adaptive Domain | Handled natively, offset written to VDB | Offset missing from VDB (Mantaflow bug) |
| Velocity | `vel.x`, `vel.y`, `vel.z` (3 scalar grids) | `velocity` (1 vec3 grid) |

In Houdini, when you use a Transform SOP on VDB primitives, the transform is applied directly to the grid's internal affine map. The VDB file always contains the complete spatial information. There is no second "object transform" that can get out of sync.

In Blender, the Volume object has both the VDB grid's internal transform AND the Blender object's transform. The final world position is `grid_transform * object_transform`. When the grid transform is incomplete (missing translation from Mantaflow), the composition produces wrong results.

---

## Performance Tips for Large VDB Sequences

### Compression

- **Blosc**: Recommended. Nearly as good as ZLIB but significantly faster. Use this in Blender's cache panel.
- **Half-Float (16-bit)**: Halves file size with acceptable quality loss for density, temperature, flame. Avoid for SDF/level set data near zero-crossing.

### Storage

- **NVMe SSD**: Essential for large sequences. VDB I/O is often the bottleneck.
- **Delayed Loading**: OpenVDB supports lazy loading — voxel data isn't loaded until accessed. The source file must remain accessible.

### Extreme Compression

- **ZibraVDB**: Up to 100x compression with GPU real-time decompression. Compresses entire sequences into a single file. Available as Houdini Labs plugin.
- **NeuralVDB (NVIDIA)**: 1-2 orders of magnitude memory reduction for extremely large datasets.

### Processing Scripts

When running openvdb scripts on large sequences:
- Use `readAllGridMetadata()` for inspection (doesn't load voxel data — fast)
- Process files sequentially to manage memory
- Back up before modifying in-place

---

## Alternative Formats

| Format | Offset Handling | Notes |
|--------|----------------|-------|
| **OpenVDB** | Same transform model (the issue is Blender, not the format) | Industry standard |
| **NanoVDB** | Same transform model as OpenVDB | GPU-native, read-only topology |
| **Field3D** | Similar grid transforms | Largely superseded by OpenVDB |
| **ZibraVDB** | Compression layer on top of OpenVDB | Not a replacement format |
| **USD (UsdVol)** | Adds two-level transform hierarchy | Interchange layer, not a volume format |

**The offset problem is NOT a format issue.** It's an application-level bug in Blender's Mantaflow exporter. Switching formats won't help.

---

## References & Sources

### Blender Bug Tracker
- [#79711 — Mantaflow: OpenVDB glitches due to Adaptive Domain](https://projects.blender.org/blender/blender/issues/79711)
- [T80382 — VDB cache moving with adaptive domain](https://developer.blender.org/T80382)
- [T80884 — Adaptive Domain slides origin](https://developer.blender.org/T80884)
- [T83990 — VDB Reimport Position jitter](https://developer.blender.org/T83990)
- [T75883 — Adaptive Domain broken for Final bakes](https://developer.blender.org/T75883)
- [#156318 / #156360 — Cycles smoke offset non-square domains (Fixed)](https://projects.blender.org/blender/blender/pulls/156360)
- [#119082 — OpenVDB import volume voxel offset](https://projects.blender.org/blender/blender/issues/119082)
- [#155904 — Cycles OpenVDB volume bounds fix](https://projects.blender.org/blender/blender/pulls/155904)

### OpenVDB Documentation
- [Transforms and Maps](https://www.openvdb.org/documentation/doxygen/transformsAndMaps.html)
- [Python Bindings](https://academysoftwarefoundation.github.io/openvdb/python.html)
- [pyopenvdb Module Reference](https://academysoftwarefoundation.github.io/openvdb/python/pyopenvdb-module.html)
- [Code Examples / Cookbook](https://www.openvdb.org/documentation/doxygen/codeExamples.html)
- [GridBase Class Reference](https://academysoftwarefoundation.github.io/openvdb/classopenvdb_1_1v9__0_1_1GridBase.html)
- [VDB File Format Deep Dive (JangaFX)](https://jangafx.com/insights/vdb-a-deep-dive)
- [vdb_tool README](https://github.com/AcademySoftwareFoundation/openvdb/blob/master/openvdb_cmd/vdb_tool/README.md)

### Blender Documentation
- [Fluid Cache Settings](https://docs.blender.org/manual/en/latest/physics/fluid/type/domain/cache.html)
- [Adaptive Domain](https://docs.blender.org/manual/en/latest/physics/fluid/type/domain/gas/adaptive_domain.html)
- [Volume Properties](https://docs.blender.org/manual/en/latest/modeling/volumes/properties.html)
- [FluidDomainSettings API](https://docs.blender.org/api/current/bpy.types.FluidDomainSettings.html)
- [VolumeGrid API](https://docs.blender.org/api/current/bpy.types.VolumeGrid.html)

### Community Discussions
- [BlenderArtists — Importing VDB Bug](https://blenderartists.org/t/importing-vdb-bug/1246141)
- [BlenderArtists — Instancing fire/smoke with Mantaflow](https://blenderartists.org/t/instancing-fire-smoke-mantaflow-openvdb-volume-object/1218731)
- [BlenderArtists — EmberGen VDB scaling/pivot issues](https://blenderartists.org/t/embergen-vdb-file-scaling-and-pivot-offset-issues-anything-solved-tips/1344199)
- [SideFX Forum — Houdini to Blender VDB](https://www.sidefx.com/forum/topic/43547/)
- [Chaos Forums — VolumeGrid jitter with VDB](https://forums.chaos.com/forum/v-ray-for-3ds-max-forums/v-ray-for-3ds-max-problems/67682-volumegrid-jitter-loading-vdb-files)
- [JangaFX Forum — EmberGen VDB wrong location](https://forums.jangafx.com/t/embergen-exported-vdb-wrong-location-and-scale-235/207)

### Windows-Specific
- [pyopenvdb on PyPI (Linux-only)](https://pypi.org/project/pyopenvdb/)
- [openvdb on conda-forge (Windows builds available)](https://anaconda.org/conda-forge/openvdb)
- [Blender devtalk — pyopenvdb bundled in Blender](https://devtalk.blender.org/t/build-pyopenvdb-as-part-of-make-deps/14148)

---

*Research compiled May 2026. Four parallel research agents covered: OpenVDB format internals, Blender Mantaflow bugs, community workarounds, and professional VFX pipeline practices. Updated with Windows-compatible instructions — all scripts use Blender's bundled openvdb module.*
