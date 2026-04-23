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
