# blender_tools

Python package of Blender 5.x pipeline tools for the IR-Unity-Research
wiki's Thread 3 (data pipeline) + Thread 4 (cinematic) playbooks.

## Install — as a Blender Extension (recommended)

One-click, no proxy, no admin, no Python-version juggling:

```bash
# Build the zip (any Python 3.11+ works; anaconda is fine)
python build_extension.py
# → dist/blender_tools-0.1.0.zip  (~55 MB, wheels bundled)

# Install into Blender 4.2+ from the command line
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --command extension install-file --repo user_default --enable dist/blender_tools-0.1.0.zip
```

Or in the GUI: **Edit → Preferences → Extensions → Install from Disk → `dist/blender_tools-0.1.0.zip`**.

Operators register under the `Blender Tools` submenu in **Add (Shift+A)** in the
3D Viewport and as `bpy.ops.blender_tools.*` from scripts.

## N-panel — one-click cinematic

After the extension is enabled, open the **3D Viewport** and press **N** to reveal
the sidebar. A new **OpenMap** tab exposes the full cinematic pipeline:

- **Build cinematic scene from region** — runs `BLENDERTOOLS_OT_full_pipeline`,
  which shells out to `workflows/full_pipeline.py` in the umbrella
  `OpenMap_Workflow` repo. Pick a region preset (e.g. `muc-sued-4x2`), choose
  datasets (`dgm1` / `dop40` / `lod2`), and Blender will load the resulting
  `.blend` when the orchestrator finishes.

The same operator is available headless as
`bpy.ops.blender_tools.full_pipeline(region="muc-sued-4x2", datasets="dgm1,dop40,lod2")`.

- **Import DOM-Mesh Slice (.glb)** — `BLENDERTOOLS_OT_import_dommesh` imports a textured
  photogrammetry-mesh slice produced by OpenMap_Unifier (`cutout.glb` + `meta.json`),
  placing it in the scene's UTM-local frame (seeding `scene["utm32n_anchor"]` if unset).

## Playbook one-liners

```python
# Thread 3 — geo import (CPython, no Blender):
from openmap_blender_tools.geo_import import reproject_geotiff
reproject_geotiff("data/raw/dop40_tile.tif", "data/processed/dop40_tile_3857.tif", "EPSG:3857")

# Thread 4 — terrain + ortho drape (inside Blender):
from openmap_blender_tools.terrain_setup import create_terrain_from_dgm, apply_ortho_drape
plane = create_terrain_from_dgm("data/processed/dgm1_merged.tif")
apply_ortho_drape(plane, "data/processed/dop40_udim.<UDIM>.tif")

# Thread 4 — LoD2 buildings (pure-Python CityGML -> CityJSON, then import):
from openmap_blender_tools.citygml_import import gml_to_cityjson_pure, import_cityjson_buildings
gml_to_cityjson_pure("data/raw/lod2_tile.gml", "data/processed/lod2_tile.json")
import_cityjson_buildings("data/processed/lod2_tile.json")

# Thread 4 — cinematic camera fly-over with constant velocity:
from openmap_blender_tools.waypoints_to_camera import build_camera_path, keyframe_constant_velocity
cam = build_camera_path([(0,0,200), (4000,0,200), (4000,2000,200)])
keyframe_constant_velocity(cam, frame_start=1, frame_end=240, speed_m_per_s=80.0)

# Thread 4 — one-call cinematic preset (Eevee Next, large-scene clipping, AA):
from openmap_blender_tools.cinematic_preset import apply_cinematic_preset, set_camera_clip_for_large_scene
apply_cinematic_preset()
set_camera_clip_for_large_scene(clip_end=20000.0)
```

## Install — as a pip package (for development)

```bash
cd research_bot/blender_tools
pip install -e .
# or with CAD extras:
pip install -e ".[cad]"
# dev dependencies:
pip install -e ".[dev]"
```

Some modules (`terrain_setup`, `citygml_import`, `world_setup`) import
`bpy` and must run inside Blender. The rest (`geo_import`,
`waypoints_to_camera`, `step_retessellate`, `cleanup_pymeshlab`,
`hidden_geo_cull`) run in plain CPython.

## CLI

```bash
blender-tools <command> [options]
```

See `blender-tools --help` for the full subcommand list.

Subcommands are wired to real implementations progressively via the
Phase 2 W6 implementation plan:
`docs/superpowers/plans/2026-04-22-phase-2-w6-blender-playbooks.md`.

## Playbooks

| Playbook | Module(s) |
|---|---|
| `[[threads/3-data-pipeline/playbooks/geo-data-types-and-blender-import]]` | `geo_import` |
| `[[threads/4-cinematic/playbooks/blender-terrain-setup]]` | `terrain_setup` |
| `[[threads/4-cinematic/playbooks/blender-vegetation-water-buildings]]` | `citygml_import`, `ndvi_scatter` |
| `[[threads/4-cinematic/playbooks/blender-cinematic-camera-rig]]` | `waypoints_to_camera` |
| `[[threads/4-cinematic/playbooks/blender-environment-atmosphere]]` | `world_setup` |
| `[[threads/4-cinematic/playbooks/cad-to-blender-rocket-pipeline]]` | `step_retessellate`, `cleanup_pymeshlab`, `hidden_geo_cull` |

## Test

```bash
pytest research_bot/blender_tools/tests/ -v
```

`bpy`-dependent tests are marked `@pytest.mark.needs_blender` and skipped
by default; run them via `blender --background --python <smoke_test>.py`.
