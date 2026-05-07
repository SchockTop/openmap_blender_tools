# Blender UI Operators — Full Feature Exposure

**Date:** 2026-05-07  
**Status:** Draft for review  

## Problem

The addon has 30+ Python functions for geo-import, scene setup, and cinematic
tools. Only 6 are exposed as Blender operators. A user opening Blender with
downloaded map data has no way to use the core features without writing Python
scripts.

## Design Goals

1. Every standalone-usable function gets a Blender operator
2. N-panel organized into collapsible sub-panels by workflow stage
3. File browser dialogs for all file inputs (Blender-native UX)
4. One-click "Quick Setup" for the common download→terrain→render flow
5. All operators work standalone — no pipeline dependency required

## Panel Layout

```
N-Panel → "OpenMap" tab
│
├── 📦 Import Data  (sub-panel, default open)
│   ├── [Import Heightmap]     .tif file browser → terrain mesh
│   ├── [Import DGM5 ZIP]     .zip file browser → convert + terrain
│   ├── [Import Orthophoto]   .tif folder browser → UDIM drape on terrain
│   ├── [Import Buildings]    .gml/.cityjson browser → building meshes
│   ├── [Import Flight Path]  .csv browser → Bezier curve  (exists)
│   └── [Import VDB Cloud]   .vdb browser → volume object
│
├── 🎨 Scene Setup  (sub-panel, default open)
│   ├── Sky Preset    [dropdown: noon|golden-hour|blue-hour|dawn|overcast|afternoon]
│   ├── Quality       [dropdown: draft|preview|final]
│   ├── [Apply Ground Shader]      procedural terrain material
│   ├── [Apply Building Textures]  roof DOP + wall PBR
│   ├── [Scatter Trees]            GN scatter from assets/trees.blend
│   ├── [Scatter Groundcover]      FPV grass/bush band
│   └── [Add Aerial Haze]         volumetric domain cube  (exists)
│
├── 🎬 Camera  (sub-panel, default collapsed)
│   ├── Camera Preset [dropdown: fpv-walk|...|aircraft-approach]
│   ├── [Setup Camera Rig]    attach camera to path with banking
│   └── [Attach to Path]      generic object→curve  (exists)
│
├── 🚀 Quick Actions  (sub-panel, default open)
│   ├── [Quick Scene from Folder]  pick a folder → auto-detect DGM/DOP/GML → full scene
│   ├── [Render Preview]           set quality=preview + render active camera
│   └── [Full Pipeline]            external orchestrator  (exists)
│
└── 🔧 Tools  (sub-panel, default collapsed)
    ├── [Cull Hidden Geometry]  (exists)
    ├── [Clean CAD Mesh]       pymeshlab filter chain
    └── [Compute NDVI]         red+NIR → density map
```

## New Operators (14 total)

### Import Operators

#### 1. BLENDERTOOLS_OT_import_heightmap
- **Trigger:** File browser → pick .tif file(s)
- **Properties:**
  - `filepath` (FILE_PATH) — heightmap GeoTIFF
  - `directory` (DIR_PATH) — or pick a folder of .tif files
  - `subdivisions` (INT, default=11) — Subsurf levels
  - `strength` (FLOAT, default=1.0) — displacement multiplier
  - `auto_size` (BOOL, default=True) — read dimensions from GeoTIFF metadata
  - `size_x`, `size_y` (FLOAT) — manual override if auto_size=False
- **Flow:**
  1. If multiple .tif selected: call `dgm_tif_to_heightmap()` to mosaic first
  2. Call `build_terrain_from_heightmap()` with the result
  3. Store `utm32n_anchor` in scene properties
- **Result:** Terrain mesh object in scene

#### 2. BLENDERTOOLS_OT_import_dgm5_zip
- **Trigger:** File browser → pick .zip file(s)
- **Properties:**
  - `directory` (DIR_PATH) — folder containing .zip files
  - `build_terrain` (BOOL, default=True) — also build mesh
  - `subdivisions` (INT, default=9) — lower default for 5m data
- **Flow:**
  1. `dgm5_xyz_to_geotiffs()` → converted .tif files
  2. If `build_terrain`: mosaic + `build_terrain_from_heightmap()`
- **Result:** Terrain mesh (or just converted .tif files on disk)

#### 3. BLENDERTOOLS_OT_import_ortho
- **Trigger:** File browser → pick folder with .tif ortho files
- **Properties:**
  - `directory` (DIR_PATH) — folder of DOP GeoTIFFs
  - `tile_resolution` (INT, default=2048) — UDIM tile px
  - `target_terrain` (STRING) — name of terrain object to drape on (default: auto-detect)
- **Flow:**
  1. Read bbox from scene `utm32n_anchor` + terrain dimensions
  2. `dop_to_udim_tiles()` → UDIM jpg tiles
  3. `apply_ortho_drape()` on the terrain object
- **Result:** Ortho material applied to terrain

#### 4. BLENDERTOOLS_OT_import_buildings
- **Trigger:** File browser → pick .gml or .cityjson
- **Properties:**
  - `filepath` (FILE_PATH)
  - `filter_glob` = "*.gml;*.xml;*.cityjson"
  - `collection_name` (STRING, default="Buildings")
- **Flow:**
  1. If .gml: `gml_to_cityjson_pure()` → temp .cityjson
  2. `cityjson_to_blender()` with scene anchor
- **Result:** Building mesh objects in collection

#### 5. BLENDERTOOLS_OT_import_vdb_cloud
- **Trigger:** File browser → pick .vdb
- **Properties:**
  - `filepath` (FILE_PATH)
  - `position` (FLOAT_VECTOR, default=(0,0,2000))
  - `scale` (FLOAT, default=500.0)
- **Flow:** `load_vdb_cloud()`
- **Result:** VDB volume object in scene

### Scene Setup Operators

#### 6. BLENDERTOOLS_OT_apply_sky_preset
- **Trigger:** Dropdown + button
- **Properties:**
  - `preset` (ENUM: noon|golden-hour|blue-hour|dawn|overcast|afternoon)
- **Flow:** `apply_sky_preset(scene, preset_name)`
- **Result:** Sun light + sky shader configured

#### 7. BLENDERTOOLS_OT_apply_quality
- **Trigger:** Dropdown + button
- **Properties:**
  - `preset` (ENUM: draft|preview|final)
- **Flow:** `apply_quality(scene, name)`
- **Result:** Resolution, samples, simplify settings applied

#### 8. BLENDERTOOLS_OT_apply_ground_shader
- **Trigger:** Button
- **Properties:**
  - `target_terrain` (STRING) — terrain object name (auto-detect)
- **Flow:** Build context dict → `features.ground_shader.apply(context)`
- **Result:** Procedural ground material on terrain

#### 9. BLENDERTOOLS_OT_apply_building_textures
- **Trigger:** Button
- **Properties:**
  - `collection_name` (STRING, default="Buildings")
- **Flow:** Build context dict → `features.buildings_textured.apply(context)`
- **Result:** Roof DOP + wall PBR materials on buildings

#### 10. BLENDERTOOLS_OT_scatter_trees
- **Trigger:** Button
- **Properties:**
  - `target_terrain` (STRING) — auto-detect
  - `density` (FLOAT, default=1.0) — density multiplier
- **Flow:** Build context dict → `features.trees.apply(context)`
- **Result:** GN scatter modifier on terrain + TreeTemplates linked

#### 11. BLENDERTOOLS_OT_scatter_groundcover
- **Trigger:** Button
- **Properties:**
  - `target_terrain` (STRING) — auto-detect
  - `target_instances` (INT, default=50000)
- **Flow:** Build context dict → `features.groundcover.apply(context)`
- **Result:** GN scatter modifier for grass/bushes near camera path

### Camera Operators

#### 12. BLENDERTOOLS_OT_apply_camera_preset
- **Trigger:** Dropdown + button
- **Properties:**
  - `preset` (ENUM: fpv-walk|fpv-bike|low-drone|mid-drone|cinematic-establishing|aircraft-approach)
- **Flow:** `apply_camera_preset(camera, preset_name, scene)`
- **Result:** Active camera configured with lens, altitude, motion blur

#### 13. BLENDERTOOLS_OT_setup_camera_rig
- **Trigger:** Button (requires a curve in scene)
- **Properties:**
  - `banking_max_deg` (FLOAT, default=8.0)
  - `speed_mps` (FLOAT, default=50.0)
- **Flow:** `attach_camera_rig(curve, banking_max_deg=...)`
- **Result:** Camera object with Follow Path + banking drivers

### Quick Action Operators

#### 14. BLENDERTOOLS_OT_quick_scene_from_folder
- **Trigger:** Folder browser
- **Properties:**
  - `directory` (DIR_PATH)
  - `sky_preset` (ENUM, default="afternoon")
  - `quality` (ENUM, default="preview")
  - `import_buildings` (BOOL, default=True)
  - `apply_ground_shader` (BOOL, default=True)
  - `scatter_trees` (BOOL, default=True)
- **Flow:**
  1. Scan folder for .tif (DGM), .tif (DOP — by size/subfolder), .gml, .zip
  2. Auto-detect what's present
  3. Run: heightmap → ortho drape → buildings → sky → ground shader → trees
  4. Create camera at cinematic-establishing altitude
  5. Frame scene
- **Result:** Complete renderable scene from a folder of geo data

### Tool Operators

Tools section keeps existing operators + adds:

#### 15. BLENDERTOOLS_OT_clean_cad_mesh
- **Trigger:** File browser → pick mesh file
- **Properties:**
  - `filepath` (FILE_PATH) — .obj/.ply/.stl/.glb
  - `output_path` (FILE_PATH) — cleaned output
- **Flow:** `clean_cad_mesh(input, output)`
- **Result:** Cleaned mesh file on disk

#### 16. BLENDERTOOLS_OT_compute_ndvi
- **Trigger:** Two file browsers (red + NIR band)
- **Properties:**
  - `red_path` (FILE_PATH)
  - `nir_path` (FILE_PATH)
  - `output_path` (FILE_PATH)
- **Flow:** `compute_ndvi()`
- **Result:** NDVI GeoTIFF on disk

## Usability Features

### Auto-detect terrain object
Many operators need a "target terrain." Helper function:
```python
def _find_terrain(context):
    # 1. Check scene["terrain_object_name"]
    # 2. Look for object named "Terrain" or in "Terrain" collection
    # 3. Look for largest mesh object with a Displace modifier
    # 4. Fall back to active object
```

### Auto-detect buildings collection
```python
def _find_buildings(context):
    # 1. Check scene["building_collection_name"]
    # 2. Look for collection named "Buildings" or "CityJSON"
    # 3. Fall back to active collection
```

### Scene properties panel
Show stored metadata in the panel header:
- `utm32n_anchor`: the coordinate anchor
- `terrain_size`: dimensions in meters
- `bbox_utm32n`: the AOI bounding box
- Import status indicators (✓ Heightmap ✓ Ortho ✗ Buildings)

### Undo support
All operators use `bl_options = {"REGISTER", "UNDO"}` so Ctrl+Z works.

### Progress reporting
Long operations (GDAL mosaic, CityGML parse) call
`context.window_manager.progress_update()` when possible, or print to
system console with `[OpenMap]` prefix for consistency.

## Files Changed

- `operators.py` — rewrite: all new operators + sub-panels + helpers
- `__init__.py` — no change (register/unregister already delegates)
- `build_extension.py` — no change (already bundles all .py files)

## Testing

1. Build extension zip: `python build_extension.py`
2. Install into Blender 5.1
3. Verify N-panel shows all sub-panels
4. Test each operator individually with real Bayern data
5. Test "Quick Scene from Folder" with a folder of downloaded tiles
