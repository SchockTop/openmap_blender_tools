"""Blender 5.x pipeline tools for terrain + cinematic rendering.

Thread 3 (data pipeline) + Thread 4 (cinematic) code scaffolds. See
`wiki/threads/3-data-pipeline/playbooks/` and
`wiki/threads/4-cinematic/playbooks/` for usage.

Modules
-------
- geo_import           : GDAL preprocess (DGM tif → EXR heightmap; DOP → UDIM).
- terrain_setup        : bpy plane + Subsurf + Displace from EXR heightmap.
- citygml_import       : LoD2 CityGML → CityJSON → Blender via Up3date.
- ndvi_scatter         : NDVI raster → Geometry-Nodes density field.
- waypoints_to_camera  : WGS84 CSV → UTM32N Bezier + Damped Track rig.
- world_setup          : Multiple Scattering sky + volumetric haze + VDB.
- step_retessellate    : pythonocc BRepMesh_IncrementalMesh → glTF.
- cleanup_pymeshlab    : Mesh hygiene chain.
- hidden_geo_cull      : Name-pattern + render-face-ID hidden-geo culling.
"""

__version__ = "0.1.0"
