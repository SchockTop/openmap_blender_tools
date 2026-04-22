# blender_tools

Python package of Blender 5.x pipeline tools for the IR-Unity-Research
wiki's Thread 3 (data pipeline) + Thread 4 (cinematic) playbooks.

## Install

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
