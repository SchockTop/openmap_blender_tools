"""DOM-Mesh slice (cutout.glb + meta.json from OpenMap_Unifier) -> Blender import.

Pure-Python entry points (`read_dommesh_meta`, `anchor_offset`) are unit-tested
without bpy. `import_dommesh_glb` is bpy-dependent: it imports the GLB via
Blender's built-in glTF importer, then translates the result so the model lands
in the scene's UTM-local frame (the OpenMap anchor system; same idea as
import_heightmap / import_buildings).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Any


def read_dommesh_meta(meta_path: str) -> dict:
    """Load the meta.json written next to cutout.glb."""
    return json.loads(Path(meta_path).read_text())


def anchor_offset(meta: dict, scene_anchor: Optional[tuple[float, float, float]]
                  ) -> tuple[float, float]:
    """How far to translate the imported (cutout-anchor-relative) vertices so
    they sit correctly in the scene's UTM-local frame.

    If the scene has no anchor yet, the caller should adopt the cutout's anchor
    as the scene anchor and import at the origin -> offset (0, 0).
    """
    if scene_anchor is None:
        return (0.0, 0.0)
    ca = meta["anchor_epsg25832"]
    return (float(ca[0]) - float(scene_anchor[0]), float(ca[1]) - float(scene_anchor[1]))


def import_dommesh_glb(glb_path: str, meta_path: Optional[str] = None,
                       scene_anchor: Optional[tuple[float, float, float]] = None
                       ) -> dict[str, Any]:
    """Import cutout.glb into the current Blender scene.

    Returns {"objects": [bpy.types.Object, ...], "empty": <parent empty>,
    "adopted_anchor": <(x,y,0) or None>}. Requires bpy.
    """
    import bpy  # noqa: PLC0415 - bpy only exists inside Blender

    # Make sure the glTF importer addon is available (it ships with Blender).
    if not hasattr(bpy.ops.import_scene, "gltf"):
        bpy.ops.preferences.addon_enable(module="io_scene_gltf2")

    meta = read_dommesh_meta(meta_path) if meta_path else {}
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb_path)
    new_objs = [o for o in bpy.data.objects if o not in before]

    adopted = None
    if scene_anchor is None and meta.get("anchor_epsg25832"):
        ca = meta["anchor_epsg25832"]
        adopted = (float(ca[0]), float(ca[1]), 0.0)
        bpy.context.scene["utm32n_anchor"] = list(adopted)

    dx, dy = anchor_offset(meta, scene_anchor) if meta else (0.0, 0.0)

    # Parent everything under one empty so the slice moves/hides as a unit.
    empty = bpy.data.objects.new("DOM-Mesh", None)
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (dx, dy, 0.0)
    for o in new_objs:
        if o.parent is None:
            o.parent = empty
        # Photogrammetry textures are colour data, not data maps.
        for slot in getattr(o, "material_slots", []):
            mat = slot.material
            if not mat or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    node.image.colorspace_settings.name = "sRGB"
    return {"objects": new_objs, "empty": empty, "adopted_anchor": adopted}
