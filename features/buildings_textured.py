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
        # Assign per-face material index based on Z-normal.
        # TODO: Prefer semantic-tag info from CityJSON parser if available
        # (RoofSurface / WallSurface / GroundSurface) instead of Z-normal heuristic.
        mesh = obj.data
        mesh.calc_loop_triangles()  # ensure normals are up to date
        for poly in mesh.polygons:
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
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 0.85
    # Load the DOP UDIM image if available.
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
