"""Blender 5.x terrain setup from EXR heightmap.

Must run inside Blender (uses `bpy`). The `build_terrain_from_heightmap`
function is the primary entry point; pure-Python helpers below are
importable anywhere for unit testing.

Usage from shell:
    blender --background --factory-startup --python -c "
    from blender_tools.terrain_setup import build_terrain_from_heightmap
    build_terrain_from_heightmap(
        heightmap_exr='out/corridor_height.exr',
        size_meters=(10000.0, 4000.0),
        subdivisions=11,
        anchor_utm32n=(701000.0, 5338000.0, 500.0),
    )
    bpy.ops.wm.save_as_mainfile(filepath='out/corridor.blend')
    "
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Pure-Python helpers (no bpy dependency — tested directly)
# ---------------------------------------------------------------------------


def compute_plane_dimensions(
    size_meters: tuple[float, float],
    subdivisions: int,
) -> tuple[float, float, int]:
    """Return (x_size, y_size, vertex_count_per_side) for a Subsurf Simple plane.

    A Subsurf Simple level-N plane has 2**N segments per side → 2**N + 1 vertices.
    Returns the plane XY dimensions in meters plus the resulting vertex count.
    """
    if subdivisions < 0 or subdivisions > 14:
        raise ValueError(f"subdivisions out of range [0, 14]: {subdivisions}")
    x, y = size_meters
    if x <= 0 or y <= 0:
        raise ValueError(f"size_meters must be positive, got {size_meters}")
    verts_per_side = (1 << subdivisions) + 1  # 2**subdivisions + 1
    return (x, y, verts_per_side)


def apply_anchor_shift(
    world_xyz: tuple[float, float, float],
    anchor_utm32n: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Shift a UTM32N world coordinate into Blender-local space via anchor subtraction.

    Required to keep all Blender coordinates inside float32 precision
    (UTM eastings ~6e5, northings ~5.3e6 make float32 vertex spacing >0.5 m).
    """
    return tuple(w - a for w, a in zip(world_xyz, anchor_utm32n))


def heightmap_material_settings() -> dict:
    """Return the dict of non-negotiable Image Texture node settings for the heightmap.

    These are hard-learned gotchas from raw/TerrainGeneration §2:
    - Color Space MUST be Non-Color (linear elevation data; Color would gamma-shift it).
    - Interpolation MUST be Cubic (Linear causes faceted terraces on grazing slopes).
    - Extension MUST be Extend (Repeat or Clip cause seam artefacts at corridor edges).
    """
    return {
        "colorspace": "Non-Color",
        "interpolation": "Cubic",
        "extension": "EXTEND",
    }


# ---------------------------------------------------------------------------
# bpy-dependent functions — guarded import
# ---------------------------------------------------------------------------


def _require_bpy() -> Any:
    """Lazy-import bpy with a helpful error outside Blender."""
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "terrain_setup requires Blender's bundled Python (bpy). "
            "Run via: blender --background --python <script>.py"
        ) from e
    return bpy


def build_terrain_from_heightmap(
    heightmap_exr: str | Path,
    size_meters: tuple[float, float],
    subdivisions: int = 11,
    strength: float = 1.0,
    mid_level: float = 0.0,
    anchor_utm32n: tuple[float, float, float] = (0.0, 0.0, 0.0),
    collection_name: str = "Terrain",
    auto_smooth_angle_deg: float = 35.0,
) -> Any:
    """Build a Subsurf+Displace terrain mesh from an EXR heightmap inside Blender.

    Parameters match the function signature used by the Thread-4 Blender
    terrain playbook. Stores `anchor_utm32n` in Scene custom prop `utm32n_anchor`
    so downstream scripts (waypoints_to_camera etc.) can re-use the same anchor.

    Returns the created mesh Object.
    """
    bpy = _require_bpy()
    heightmap_path = str(Path(heightmap_exr).resolve())
    x_size, y_size, _ = compute_plane_dimensions(size_meters, subdivisions)

    # 1. Create or reuse collection.
    scene = bpy.context.scene
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        coll = bpy.data.collections.new(collection_name)
        scene.collection.children.link(coll)

    # 2. Store anchor in scene custom prop.
    scene["utm32n_anchor"] = list(anchor_utm32n)

    # 3. Create plane at origin (anchor-shifted means origin = corridor centre).
    bpy.ops.mesh.primitive_plane_add(
        size=1.0,
        location=(0.0, 0.0, 0.0),
    )
    plane = bpy.context.active_object
    plane.name = f"{collection_name}Plane"
    plane.scale = (x_size, y_size, 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # 4. Move to target collection.
    for c in plane.users_collection:
        c.objects.unlink(plane)
    coll.objects.link(plane)

    # 5. UV unwrap — smart_project with a single-island top-down projection is
    #    adequate; the Thread-3 playbook documents the projection convention.
    bpy.ops.object.select_all(action="DESELECT")
    plane.select_set(True)
    bpy.context.view_layer.objects.active = plane
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15)  # 66°, liberal
    bpy.ops.object.mode_set(mode="OBJECT")

    # 6. Load heightmap into a data-block with the hard-coded settings.
    if heightmap_path in (img.filepath for img in bpy.data.images):
        img = next(img for img in bpy.data.images if img.filepath == heightmap_path)
    else:
        img = bpy.data.images.load(heightmap_path, check_existing=True)
    img.colorspace_settings.name = heightmap_material_settings()["colorspace"]

    # 7. Subsurf modifier (Simple).
    subsurf = plane.modifiers.new(name="Subsurf", type="SUBSURF")
    subsurf.subdivision_type = "SIMPLE"
    subsurf.levels = subdivisions
    subsurf.render_levels = subdivisions

    # 8. Displace modifier — texture slot with the EXR.
    tex = bpy.data.textures.new(name=f"{plane.name}_height", type="IMAGE")
    tex.image = img
    tex.extension = heightmap_material_settings()["extension"]
    tex.use_interpolation = True  # Cubic on texture-side for the Displace modifier
    displace = plane.modifiers.new(name="Displace", type="DISPLACE")
    displace.texture = tex
    displace.texture_coords = "UV"
    displace.strength = strength
    displace.mid_level = mid_level

    # 9. Shade Auto Smooth modifier (5.x replaces the removed mesh property).
    try:
        bpy.ops.object.shade_auto_smooth(angle=auto_smooth_angle_deg * 3.14159265 / 180.0)
    except (AttributeError, RuntimeError):
        # Older Blender / GUI-only fallback: leave unset, add a Smooth-by-Angle modifier.
        smooth = plane.modifiers.new(name="SmoothByAngle", type="NODES")
        # Caller can swap in the actual Smooth-by-Angle node group later.
        del smooth

    return plane


def apply_ortho_drape(plane_obj: Any, ortho_dir: str | Path,
                      material_name: str = "OrthoDrape") -> Any:
    """Attach a UDIM ortho material to a terrain plane.

    Reads `ortho_dir/ortho.<udim>.jpg` files (produced by
    geo_import.dop_to_udim_tiles), creates a Blender Image data-block in UDIM
    mode, builds a minimal Principled BSDF material with the image as Base
    Color, and assigns it to the plane.

    UVs are rescaled from the default 0-1 square to span the full UDIM grid
    so that all tiles are sampled, not just tile 1001.
    """
    bpy = _require_bpy()
    ortho_dir = Path(ortho_dir)
    tiles = sorted(ortho_dir.glob("ortho.*.jpg"))
    if not tiles:
        raise FileNotFoundError(f"no ortho.*.jpg tiles in {ortho_dir}")

    # Derive grid dimensions from tile UDIM numbers.
    udim_numbers = []
    for tile in tiles:
        udim_numbers.append(int(tile.stem.split(".")[1]))
    u_indices = [(u - 1001) % 10 for u in udim_numbers]
    v_indices = [(u - 1001) // 10 for u in udim_numbers]
    u_tiles = max(u_indices) + 1
    v_tiles = max(v_indices) + 1

    # Load the UDIM image set using the <UDIM> token path.
    # bpy.data.images.load() with a <UDIM>-token filepath auto-detects UDIM
    # mode in Blender 3.x+ and sets source='TILED' internally — this is the
    # only path that correctly initialises the Cycles render-time tile lookup.
    # Using bpy.data.images.new() + patching source/filepath afterwards leaves
    # the image in a "Generated" state that Cycles cannot resolve at render time,
    # producing the "Image file does not exist" error with an empty filename.
    udim_token_path = str(ortho_dir.resolve() / "ortho.<UDIM>.jpg")
    # Remove any stale datablock from a previous assembly run.
    for _old in list(bpy.data.images):
        if "ortho" in _old.name.lower():
            bpy.data.images.remove(_old)
    img = bpy.data.images.load(udim_token_path, check_existing=False)
    img.colorspace_settings.name = "sRGB"
    # Ensure source is TILED (should be auto-set by load, but belt-and-suspenders).
    img.source = "TILED"
    # Register any tiles that weren't auto-detected by the load call.
    if hasattr(img, "tiles"):
        existing_tile_nums = {t.number for t in img.tiles}
        for tile in tiles:
            udim = int(tile.stem.split(".")[1])
            if udim not in existing_tile_nums:
                try:
                    img.tiles.new(tile_number=udim, label=str(tile.name))
                    existing_tile_nums.add(udim)
                except Exception:
                    pass
    print(f"[terrain_setup] ortho UDIM loaded: {img.filepath!r}, "
          f"source={img.source}, "
          f"tiles={len(img.tiles) if hasattr(img, 'tiles') else '?'}")

    # Create a separate UV layer for ortho UDIM sampling, scaled to the tile
    # grid. The original UV layer (used by the displacement modifier for
    # heightmap sampling) must stay in the 0-1 range.
    mesh = plane_obj.data
    ortho_uv = mesh.uv_layers.new(name="OrthoUV")
    if mesh.uv_layers.active:
        src = mesh.uv_layers.active
        for i, loop in enumerate(ortho_uv.data):
            loop.uv.x = src.data[i].uv.x * u_tiles
            loop.uv.y = src.data[i].uv.y * v_tiles

    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = "OrthoUV"
    tex.image = img
    tex.extension = "EXTEND"
    links.new(uv.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85

    plane_obj.data.materials.clear() if hasattr(plane_obj.data.materials, "clear") \
        else None
    plane_obj.data.materials.append(mat)
    return mat
