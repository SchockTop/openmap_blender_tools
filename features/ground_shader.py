"""ground_shader.py — multi-layer procedural ground material for terrain.

Blends grass / rock / forest-floor / field via slope, altitude, and (optional)
NDVI sampling. If the terrain already has a DOP-drape material, the procedural
layers are mixed IN as detail (multiplicative); otherwise they're standalone.

Pure procedural — Voronoi for cobble/dirt, Noise for variation, no assets.
"""
from __future__ import annotations
from typing import Any

NAME = "ground-shader"
DESCRIPTION = "Multi-layer procedural ground (grass/rock/forest/field) blended by slope + altitude"


def apply(context):
    bpy = context["bpy"]
    terrain = context.get("terrain_obj")
    if terrain is None:
        print("[ground-shader] no terrain in context; skip")
        return {}

    existing_mat = terrain.data.materials[0] if (terrain.data.materials and
                                                 terrain.data.materials[0]) else None
    is_combine_mode = existing_mat is not None and existing_mat.name.startswith("OrthoDrape")

    mat = _build_procedural_ground_material(bpy, base_image_material=existing_mat
                                            if is_combine_mode else None)
    terrain.data.materials.clear()
    terrain.data.materials.append(mat)
    print(f"[ground-shader] material '{mat.name}' attached "
          f"({'combined with DOP drape' if is_combine_mode else 'standalone procedural'})")
    return {"ground_shader_material": mat.name,
            "ground_shader_combined_with_drape": is_combine_mode}


def _build_procedural_ground_material(bpy, base_image_material=None):
    name = "GroundShader_Layered"
    if name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[name])
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    links = nt.links

    # --- Layer 1: Grass (Noise + green colorramp) ---
    grass_noise = nt.nodes.new("ShaderNodeTexNoise"); grass_noise.location = (-1200, 600)
    grass_noise.inputs["Scale"].default_value = 60.0
    grass_noise.inputs["Detail"].default_value = 8.0
    grass_ramp = nt.nodes.new("ShaderNodeValToRGB"); grass_ramp.location = (-1000, 600)
    grass_ramp.color_ramp.elements[0].color = (0.18, 0.32, 0.10, 1)
    grass_ramp.color_ramp.elements[1].color = (0.35, 0.55, 0.18, 1)
    nt.links.new(grass_noise.outputs["Fac"], grass_ramp.inputs["Fac"])

    # --- Layer 2: Rock (Voronoi + grey ramp) ---
    rock_voro = nt.nodes.new("ShaderNodeTexVoronoi"); rock_voro.location = (-1200, 300)
    rock_voro.inputs["Scale"].default_value = 25.0
    rock_ramp = nt.nodes.new("ShaderNodeValToRGB"); rock_ramp.location = (-1000, 300)
    rock_ramp.color_ramp.elements[0].color = (0.42, 0.40, 0.38, 1)
    rock_ramp.color_ramp.elements[1].color = (0.58, 0.55, 0.50, 1)
    nt.links.new(rock_voro.outputs["Distance"], rock_ramp.inputs["Fac"])

    # --- Layer 3: Forest floor (Noise + dark brown) ---
    forest_noise = nt.nodes.new("ShaderNodeTexNoise"); forest_noise.location = (-1200, 0)
    forest_noise.inputs["Scale"].default_value = 100.0
    forest_ramp = nt.nodes.new("ShaderNodeValToRGB"); forest_ramp.location = (-1000, 0)
    forest_ramp.color_ramp.elements[0].color = (0.18, 0.12, 0.06, 1)
    forest_ramp.color_ramp.elements[1].color = (0.30, 0.22, 0.14, 1)
    nt.links.new(forest_noise.outputs["Fac"], forest_ramp.inputs["Fac"])

    # --- Layer 4: Field (Wave texture for parallel furrows + earthy ochre/brown) ---
    field_wave = nt.nodes.new("ShaderNodeTexWave"); field_wave.location = (-1200, -300)
    field_wave.wave_type = "BANDS"
    try:
        field_wave.bands_direction = "X"
    except (AttributeError, TypeError):
        pass  # older Blender API may not have bands_direction
    field_wave.inputs["Scale"].default_value = 8.0
    field_wave.inputs["Distortion"].default_value = 1.5
    field_wave.inputs["Detail"].default_value = 5.0
    field_wave.inputs["Detail Scale"].default_value = 1.0

    # Two-color ramp: wet brown (low) -> dry ochre (high)
    field_ramp = nt.nodes.new("ShaderNodeValToRGB"); field_ramp.location = (-1000, -300)
    # Position the elements wider for sharper furrow contrast.
    field_ramp.color_ramp.elements[0].position = 0.3
    field_ramp.color_ramp.elements[0].color = (0.42, 0.30, 0.18, 1)  # wet brown furrow base
    field_ramp.color_ramp.elements[1].position = 0.7
    field_ramp.color_ramp.elements[1].color = (0.65, 0.55, 0.32, 1)  # dry ochre crest
    nt.links.new(field_wave.outputs["Color"], field_ramp.inputs["Fac"])

    # --- Slope mask via Geometry > Normal ---
    geom = nt.nodes.new("ShaderNodeNewGeometry"); geom.location = (-1500, -100)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-1300, -100)
    nt.links.new(geom.outputs["Normal"], sep.inputs["Vector"])
    slope_invert = nt.nodes.new("ShaderNodeMath"); slope_invert.location = (-1100, -100)
    slope_invert.operation = "SUBTRACT"
    slope_invert.inputs[0].default_value = 1.0
    nt.links.new(sep.outputs["Z"], slope_invert.inputs[1])
    slope_ramp = nt.nodes.new("ShaderNodeValToRGB"); slope_ramp.location = (-900, -100)
    slope_ramp.color_ramp.elements[0].position = 0.15
    slope_ramp.color_ramp.elements[1].position = 0.45
    nt.links.new(slope_invert.outputs["Value"], slope_ramp.inputs["Fac"])

    # --- Mix grass+rock by slope ---
    mix_gr_rk = nt.nodes.new("ShaderNodeMixRGB"); mix_gr_rk.location = (-700, 400)
    mix_gr_rk.blend_type = "MIX"
    nt.links.new(slope_ramp.outputs["Color"], mix_gr_rk.inputs["Fac"])
    nt.links.new(grass_ramp.outputs["Color"], mix_gr_rk.inputs["Color1"])
    nt.links.new(rock_ramp.outputs["Color"], mix_gr_rk.inputs["Color2"])

    # --- Mix in forest floor by procedural noise mask ---
    forest_mask_noise = nt.nodes.new("ShaderNodeTexNoise"); forest_mask_noise.location = (-700, 100)
    forest_mask_noise.inputs["Scale"].default_value = 4.0
    forest_mask_noise.inputs["Detail"].default_value = 2.0
    forest_mask_ramp = nt.nodes.new("ShaderNodeValToRGB"); forest_mask_ramp.location = (-500, 100)
    forest_mask_ramp.color_ramp.elements[0].position = 0.55
    forest_mask_ramp.color_ramp.elements[1].position = 0.7
    nt.links.new(forest_mask_noise.outputs["Fac"], forest_mask_ramp.inputs["Fac"])
    mix_fr = nt.nodes.new("ShaderNodeMixRGB"); mix_fr.location = (-300, 200)
    mix_fr.blend_type = "MIX"
    nt.links.new(forest_mask_ramp.outputs["Color"], mix_fr.inputs["Fac"])
    nt.links.new(mix_gr_rk.outputs["Color"], mix_fr.inputs["Color1"])
    nt.links.new(forest_ramp.outputs["Color"], mix_fr.inputs["Color2"])

    # --- Mix in field by altitude ---
    sep_pos = nt.nodes.new("ShaderNodeSeparateXYZ"); sep_pos.location = (-1500, -400)
    nt.links.new(geom.outputs["Position"], sep_pos.inputs["Vector"])
    field_alt_ramp = nt.nodes.new("ShaderNodeValToRGB"); field_alt_ramp.location = (-1100, -400)
    field_alt_ramp.color_ramp.elements[0].position = 0.0
    field_alt_ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    field_alt_ramp.color_ramp.elements[1].position = 0.6
    field_alt_ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    field_div = nt.nodes.new("ShaderNodeMath"); field_div.location = (-1300, -400)
    field_div.operation = "DIVIDE"; field_div.inputs[1].default_value = 100.0
    nt.links.new(sep_pos.outputs["Z"], field_div.inputs[0])
    nt.links.new(field_div.outputs["Value"], field_alt_ramp.inputs["Fac"])
    mix_field = nt.nodes.new("ShaderNodeMixRGB"); mix_field.location = (-100, 0)
    mix_field.blend_type = "MIX"
    nt.links.new(field_alt_ramp.outputs["Color"], mix_field.inputs["Fac"])
    nt.links.new(mix_fr.outputs["Color"], mix_field.inputs["Color1"])
    nt.links.new(field_ramp.outputs["Color"], mix_field.inputs["Color2"])

    # --- BSDF + Output ---
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
    bsdf.inputs["Roughness"].default_value = 0.95
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)

    final_color_socket = mix_field.outputs["Color"]

    # --- Optional: combine with DOP drape ---
    if base_image_material is not None:
        img_node = next((n for n in base_image_material.node_tree.nodes
                        if n.type == "TEX_IMAGE" and n.image is not None), None)
        if img_node is not None:
            uv = nt.nodes.new("ShaderNodeUVMap"); uv.location = (-1500, 600)
            tex = nt.nodes.new("ShaderNodeTexImage"); tex.location = (-1300, 600)
            tex.image = img_node.image; tex.extension = "EXTEND"
            nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
            mix_drape = nt.nodes.new("ShaderNodeMixRGB"); mix_drape.location = (300, -200)
            mix_drape.blend_type = "MULTIPLY"
            mix_drape.inputs["Fac"].default_value = 0.6
            nt.links.new(tex.outputs["Color"], mix_drape.inputs["Color1"])
            nt.links.new(final_color_socket, mix_drape.inputs["Color2"])
            final_color_socket = mix_drape.outputs["Color"]

    nt.links.new(final_color_socket, bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat
