"""build_trees.py — rebuild assets/trees.blend from Polyhaven CC0 sources.

Run interactively from inside Blender 5.1 (NOT in --background):

  Scripting workspace -> Open this file -> Run Script.

Requires:
  - The BlenderMCP add-on (https://github.com/ahujasid/blender-mcp) installed
    AND the 'Use assets from Poly Haven' checkbox enabled. The add-on does
    the actual download via Polyhaven's API.
  - OR: alternatively download the four .blend files manually from Polyhaven
    and edit DOWNLOAD_BLENDS below.

This script is the source of truth for what goes into trees.blend. The
file was originally built via the BlenderMCP integration; this captures
the same recipe so anyone with Blender can re-run it.
"""
from __future__ import annotations
import bpy
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
TARGET = ASSETS_DIR / "trees.blend"

# (target_template_name, polyhaven_asset_id)
SPECIES = [
    ("TreeTpl_Oak",    "island_tree_02"),
    ("TreeTpl_Beech",  "island_tree_03"),
    ("TreeTpl_Spruce", "fir_tree_01"),
    ("TreeTpl_Birch",  "jacaranda_tree"),
]

# Initial decimation ratio (compounded twice = ~5% of LOD0 polys).
DECIMATE_RATIO_PASS1 = 0.10
DECIMATE_RATIO_PASS2 = 0.50

# Texture resolutions kept (everything else dropped).
LEAF_TEX_SIZE = 1024   # silhouette critical
TRUNK_TEX_SIZE = 512


def _clear_scene():
    """Non-destructive clear: remove objects/data without factory reset
    (factory reset unloads addons including BlenderMCP)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for img in list(bpy.data.images):
        bpy.data.images.remove(img, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)


def _import_polyhaven(asset_id: str):
    """Trigger Polyhaven import via the BlenderMCP operator if available.

    If the add-on isn't installed, this raises — the user is expected to
    install BlenderMCP or download the assets manually.
    """
    try:
        # Operator name as registered by the BlenderMCP add-on.
        bpy.ops.blendermcp.download_polyhaven_asset(
            asset_id=asset_id, asset_type="models", resolution="1k")
    except (AttributeError, RuntimeError):
        raise RuntimeError(
            f"Could not import {asset_id}: the BlenderMCP add-on isn't available. "
            "Install it from https://github.com/ahujasid/blender-mcp or download "
            f"https://polyhaven.com/a/{asset_id} manually and append the LOD0 mesh."
        )


def _rename_imported_to(target_name: str, polyhaven_id: str):
    """Find the just-imported LOD0 mesh and rename it. If the asset comes as
    multiple objects (e.g. fir_tree_01_a/b/c), keep only the first."""
    candidates = [o for o in bpy.data.objects
                  if polyhaven_id in o.name and "_LOD0" in o.name]
    if not candidates:
        raise RuntimeError(f"no LOD0 imported for {polyhaven_id}")
    keep = sorted(candidates, key=lambda o: o.name)[0]
    keep.name = target_name
    if keep.data is not None:
        keep.data.name = target_name
    keep.location = (0.0, 0.0, 0.0)
    # Remove extras.
    for extra in candidates[1:]:
        bpy.data.objects.remove(extra, do_unlink=True)
    return keep


def _organize_into_collection():
    coll_name = "TreeTemplates"
    if coll_name in bpy.data.collections:
        coll = bpy.data.collections[coll_name]
    else:
        coll = bpy.data.collections.new(coll_name)
        bpy.context.scene.collection.children.link(coll)
    coll.hide_viewport = True
    coll.hide_render = True
    for tpl_name, _ in SPECIES:
        obj = bpy.data.objects.get(tpl_name)
        if obj is None:
            continue
        for c in list(obj.users_collection):
            if c is not coll:
                try: c.objects.unlink(obj)
                except Exception: pass
        if obj.name not in coll.objects:
            coll.objects.link(obj)


def _decimate_all():
    for tpl_name, _ in SPECIES:
        obj = bpy.data.objects.get(tpl_name)
        if obj is None:
            continue
        for ratio in (DECIMATE_RATIO_PASS1, DECIMATE_RATIO_PASS2):
            mod = obj.modifiers.new(f"Dec_{ratio}", type="DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)


def _strip_nonessential_textures():
    # Disconnect non-color maps from materials.
    for mat in bpy.data.materials:
        if not mat.use_nodes or mat.node_tree is None:
            continue
        for node in list(mat.node_tree.nodes):
            if node.type == "TEX_IMAGE" and node.image is not None:
                nm = node.image.name.lower()
                if "_nor_gl" in nm or "_rough" in nm or "_disp" in nm or "_ao" in nm:
                    node.image = None
    # Purge orphaned images.
    for img in list(bpy.data.images):
        if img.users == 0:
            bpy.data.images.remove(img)
    # Downscale survivors.
    for img in bpy.data.images:
        if img.size[0] == 0:
            continue
        nm = img.name.lower()
        target = LEAF_TEX_SIZE if ("leaf" in nm or "leaves" in nm) else TRUNK_TEX_SIZE
        if img.size[0] > target:
            img.scale(target, target)


def main():
    _clear_scene()
    for target_name, polyhaven_id in SPECIES:
        print(f"[build_trees] importing {polyhaven_id} as {target_name}")
        _import_polyhaven(polyhaven_id)
        _rename_imported_to(target_name, polyhaven_id)
    _organize_into_collection()
    _decimate_all()
    _strip_nonessential_textures()
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(TARGET), copy=False, compress=True)
    size_mb = TARGET.stat().st_size / 1024 / 1024
    print(f"[build_trees] saved {TARGET} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
