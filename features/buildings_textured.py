"""buildings_textured.py — DOP-projected roofs + procedural PBR walls for LoD2 buildings.

Scans context['building_objs'] for CityJSON_* meshes. For each: splits faces
into roof/wall/ground by Z-normal heuristic, assigns 3 material slots:

  Slot 0 - "BldRoof_DOP"  -> top-projected DOP UDIM ortho (real roof texture)
  Slot 1 - "BldWall_PBR"  -> procedural brick + plaster shader
  Slot 2 - "BldGround"    -> transparent

Idempotent: re-running on a scene with already-textured buildings is a no-op.
"""
from __future__ import annotations
NAME = "buildings-textured"
DESCRIPTION = "DOP-projected roofs + procedural PBR walls on LoD2 buildings"


def apply(context):
    bpy = context["bpy"]
    buildings = context.get("building_objs") or []
    bbox = context.get("bbox_utm32n")
    ortho_dir = context.get("ortho_dir")
    if not buildings:
        print("[buildings-textured] no buildings in context; skip")
        return {}

    roof_mat = _make_roof_material(bpy, bbox, ortho_dir)
    wall_mat = _make_wall_material(bpy)
    ground_mat = _make_transparent_material(bpy)

    n = 0
    for obj in buildings:
        if obj.type != "MESH" or not obj.name.startswith("CityJSON_"):
            continue
        # Reset material slots.
        obj.data.materials.clear()
        obj.data.materials.append(roof_mat)
        obj.data.materials.append(wall_mat)
        obj.data.materials.append(ground_mat)
        # Prefer semantic surface info from the CityJSON parser when present
        # (face attribute "semantic_surface" — int slot 0/1/2 from
        # citygml_import.TYPE_TO_SLOT, or -1 = unknown). Fall back to Z-normal
        # heuristic per-face when the attribute is missing or carries -1.
        mesh = obj.data
        mesh.calc_loop_triangles()  # ensure normals are up to date
        sem_attr = None
        attrs = getattr(mesh, "attributes", None)
        # Guard against MagicMock attributes in tests: only accept a real
        # Blender attributes collection (has __contains__) and only use it when
        # the attribute is actually present.
        if attrs is not None and hasattr(attrs, "__contains__"):
            try:
                if "semantic_surface" in attrs:
                    sem_attr = attrs.get("semantic_surface")
            except Exception:
                sem_attr = None
        for i, poly in enumerate(mesh.polygons):
            slot = -1
            if sem_attr is not None:
                try:
                    raw = sem_attr.data[i].value
                    if isinstance(raw, int):
                        slot = raw
                except Exception:
                    slot = -1
            if slot in (0, 1, 2):
                poly.material_index = slot
                continue
            nz = poly.normal.z
            if nz > 0.7:
                poly.material_index = 0  # roof
            elif abs(nz) < 0.3:
                poly.material_index = 1  # wall
            else:
                poly.material_index = 2  # ground / sloped
        n += 1
    print(f"[buildings-textured] textured {n} building(s)")
    return {"buildings_textured_count": n}


def _make_roof_material(bpy, bbox, ortho_dir):
    """Roof material — DOP-projected ortho TINTED with warm German tile palette.

    The München DOP is mostly grey/concrete from above, so we Mix the DOP
    color with a saturated red-orange tile color (terra-cotta) so roofs
    visually read as roofs at any altitude. Per-building colour variation via
    Object Info > Random hue shift.
    """
    name = "BldRoof_DOP"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    mapping = nt.nodes.new("ShaderNodeMapping")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])

    # Warm tile palette (terra-cotta red-orange). Mixed with DOP for variation.
    tile_color = nt.nodes.new("ShaderNodeRGB")
    tile_color.outputs[0].default_value = (0.62, 0.30, 0.20, 1.0)  # warm terra-cotta (less aggressive red)

    # Per-building hue jitter so roofs aren't all identical.
    obj_info = nt.nodes.new("ShaderNodeObjectInfo")
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 1.2
    nt.links.new(tile_color.outputs[0], hsv.inputs["Color"])
    nt.links.new(obj_info.outputs["Random"], hsv.inputs["Hue"])

    # Mix DOP (when available) with the tile color (DOP gives variation, tile gives warm hue).
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 0.7   # tile dominant; DOP just adds detail
    nt.links.new(hsv.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(tex.outputs["Color"], mix.inputs["Color2"])

    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 0.85

    # Load the DOP UDIM image if available; if not, the tile color stands alone
    # (the MULTIPLY against a white-ish missing texture still works).
    if ortho_dir:
        from pathlib import Path
        tiles = sorted(Path(ortho_dir).glob("ortho.*.jpg"))
        if tiles:
            img = bpy.data.images.load(str(tiles[0]), check_existing=True)
            img.source = "TILED"
            for t in tiles[1:]:
                udim = int(t.stem.split(".")[1])
                try:
                    img.tiles.new(tile_number=udim, label=t.name)
                except Exception:
                    pass
            tex.image = img
    else:
        # No DOP: bypass the multiply, use tile color directly.
        nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def _make_wall_material(bpy):
    name = "BldWall_PBR"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    brick = nt.nodes.new("ShaderNodeTexBrick")
    object_info = nt.nodes.new("ShaderNodeObjectInfo")
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    nt.links.new(brick.outputs["Color"], hsv.inputs["Color"])
    nt.links.new(object_info.outputs["Random"], hsv.inputs["Hue"])
    nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    # German residential beige defaults.
    brick.inputs["Color1"].default_value = (0.78, 0.72, 0.62, 1)
    brick.inputs["Color2"].default_value = (0.85, 0.78, 0.68, 1)
    brick.inputs["Mortar"].default_value = (0.55, 0.5, 0.42, 1)
    brick.inputs["Scale"].default_value = 8.0
    bsdf.inputs["Roughness"].default_value = 0.95
    return mat


def _make_transparent_material(bpy):
    name = "BldGround"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    nt.links.new(transp.outputs["BSDF"], out.inputs["Surface"])
    return mat
