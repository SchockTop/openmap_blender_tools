"""clouds.py — procedural volumetric cumulus + optional cirrus layer.

A large flat box mesh with a volume-only Principled Volume material driven by
layered Noise textures thresholded by a coverage control. No external assets.

The cloud box sits in scene-local space: Allgäu terrain is ~750–1800 m ASL,
highest peaks ~2000 m, so a base_altitude_m of 2300 puts the bottom just above
the peaks. Scene-local Z = metres above sea level (the anchor only shifts X/Y).
"""
from __future__ import annotations

from typing import Any

NAME = "clouds"
DESCRIPTION = "Procedural volumetric cumulus deck (+ optional cirrus); no external assets"

_DEFAULT_XY = 20_000.0  # fallback box extent when terrain bbox is unavailable


def apply(
    context: dict[str, Any],
    *,
    coverage: float = 0.45,
    base_altitude_m: float = 2300.0,
    thickness_m: float = 600.0,
    density: float = 0.06,
    detail: float = 0.5,
    wind_dir_deg: float = 0.0,
    cirrus: bool = True,
    cirrus_altitude_m: float = 6500.0,
) -> dict[str, Any]:
    """Create procedural volumetric cloud volumes in the current scene.

    Args:
        context: feature context dict (must contain 'bpy').
        coverage: 0–1; higher = more cloud cover (lower density threshold).
        base_altitude_m: scene-local Z of the cloud-deck bottom, in metres.
        thickness_m: vertical extent of the cumulus deck.
        density: overall scatter density scalar.
        detail: 0–1; how much fine-detail noise to mix in.
        wind_dir_deg: static wind offset direction in degrees (XY plane).
        cirrus: if True, add a thin high-altitude cirrus layer.
        cirrus_altitude_m: scene-local Z of the cirrus layer bottom.

    Returns:
        dict with keys 'cumulus_object' and (optionally) 'cirrus_object'.
    """
    bpy = context["bpy"]

    size_x, size_y = _terrain_xy_extent(context)

    cumulus = _make_cloud_box(
        bpy,
        name="Clouds_Cumulus",
        size_x=size_x * 1.5,
        size_y=size_y * 1.5,
        thickness=thickness_m,
        base_z=base_altitude_m,
    )
    cumulus.data.materials.append(
        _make_cumulus_material(
            bpy,
            coverage=coverage,
            density=density,
            detail=detail,
            wind_dir_deg=wind_dir_deg,
        )
    )
    _tune_volume_step_rate(bpy)

    result: dict[str, Any] = {"cumulus_object": cumulus.name}

    if cirrus:
        cir = _make_cloud_box(
            bpy,
            name="Clouds_Cirrus",
            size_x=size_x * 2.0,
            size_y=size_y * 2.0,
            thickness=150.0,
            base_z=cirrus_altitude_m,
        )
        cir.data.materials.append(_make_cirrus_material(bpy, wind_dir_deg=wind_dir_deg))
        result["cirrus_object"] = cir.name

    print(f"[clouds] cumulus at Z={base_altitude_m:.0f} m, "
          f"thickness={thickness_m:.0f} m, coverage={coverage:.2f}")
    return result


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _terrain_xy_extent(context: dict[str, Any]) -> tuple[float, float]:
    """Return (size_x, size_y) from scene bbox or terrain object bounding box."""
    bbox = context.get("bbox_utm32n")
    if bbox and len(bbox) == 4:
        return float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])

    terrain = context.get("terrain_obj")
    if terrain is not None:
        try:
            dims = terrain.dimensions
            if dims.x > 1.0 and dims.y > 1.0:
                return float(dims.x), float(dims.y)
        except Exception:
            pass

    bpy = context["bpy"]
    try:
        scene = bpy.context.scene
        for obj in scene.objects:
            if getattr(obj, "type", None) == "MESH":
                nm = obj.name.lower()
                if nm.startswith(("terrain", "ground", "plane")):
                    dims = obj.dimensions
                    if dims.x > 1.0 and dims.y > 1.0:
                        return float(dims.x), float(dims.y)
    except Exception:
        pass

    return _DEFAULT_XY, _DEFAULT_XY


def _make_cloud_box(
    bpy,
    name: str,
    size_x: float,
    size_y: float,
    thickness: float,
    base_z: float,
) -> Any:
    """Create (or replace) a box mesh to serve as a volume domain."""
    existing = bpy.data.objects.get(name)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    center_z = base_z + thickness * 0.5
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, center_z))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size_x, size_y, thickness)
    bpy.ops.object.transform_apply(scale=True)

    # Wireframe display so the box doesn't clutter the viewport.
    obj.display_type = "WIRE"
    obj.hide_render = False

    return obj


# ---------------------------------------------------------------------------
# Node-socket helpers (Blender 5.x uses index-based socket access)
# ---------------------------------------------------------------------------

def _out(node, name_or_idx):
    """Get output socket by name, falling back to index if name lookup fails."""
    try:
        return node.outputs[name_or_idx]
    except (KeyError, IndexError):
        pass
    if isinstance(name_or_idx, str):
        return node.outputs[0]
    raise


def _inp(node, name_or_idx):
    """Get input socket by name, falling back to index if name lookup fails."""
    try:
        return node.inputs[name_or_idx]
    except (KeyError, IndexError):
        pass
    if isinstance(name_or_idx, str):
        return node.inputs[0]
    raise


def _new_mix_rgb(nt):
    """Create a colour-mix node compatible with Blender 4.x and 5.x."""
    # Blender 4.0+ replaced ShaderNodeMixRGB with ShaderNodeMix (data_type=RGBA).
    for type_name in ("ShaderNodeMixRGB", "ShaderNodeMix"):
        try:
            n = nt.nodes.new(type_name)
            if type_name == "ShaderNodeMix":
                n.data_type = "RGBA"
            return n
        except Exception:
            continue
    raise RuntimeError("Cannot create a colour-mix node in this Blender version")


def _mix_set_fac(node, value: float) -> None:
    """Set the Fac/Factor input of a mix node (name varies by version)."""
    for name in ("Fac", "Factor"):
        if name in node.inputs:
            node.inputs[name].default_value = value
            return


def _mix_inp_a(node):
    """Return the A/Color1 input socket of a mix node."""
    for name in ("Color1", "A"):
        if name in node.inputs:
            return node.inputs[name]
    return node.inputs[1]


def _mix_inp_b(node):
    """Return the B/Color2 input socket of a mix node."""
    for name in ("Color2", "B"):
        if name in node.inputs:
            return node.inputs[name]
    return node.inputs[2]


def _mix_out_color(node):
    """Return the Color/Result output socket of a mix node."""
    for name in ("Color", "Result"):
        if name in node.outputs:
            return node.outputs[name]
    return node.outputs[0]


# ---------------------------------------------------------------------------
# Material builders
# ---------------------------------------------------------------------------

def _make_cumulus_material(
    bpy,
    coverage: float,
    density: float,
    detail: float,
    wind_dir_deg: float,
) -> Any:
    import math

    mat_name = "CloudCumulus_Vol"
    if mat_name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[mat_name])

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    links = nt.links

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1200, 0)

    principled_vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    principled_vol.location = (900, 0)
    principled_vol.inputs["Anisotropy"].default_value = 0.45
    try:
        # Emission colour: very slight warm tint (sunlit cloud interior).
        principled_vol.inputs["Emission Color"].default_value = (1.0, 0.97, 0.92, 1.0)
        principled_vol.inputs["Emission Strength"].default_value = 0.0
    except KeyError:
        pass

    links.new(principled_vol.outputs["Volume"], out.inputs["Volume"])

    # --- Texture coordinate: Object space of the cloud box itself ---
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1400, 0)

    # Static wind offset vector derived from wind_dir_deg.
    wind_rad = math.radians(wind_dir_deg)
    wind_x = math.cos(wind_rad) * 500.0
    wind_y = math.sin(wind_rad) * 500.0
    add_wind = nt.nodes.new("ShaderNodeVectorMath")
    add_wind.operation = "ADD"
    add_wind.location = (-1200, 0)
    add_wind.inputs[1].default_value = (wind_x, wind_y, 0.0)
    links.new(tex_coord.outputs["Object"], add_wind.inputs[0])

    # --- Large-scale shape noise (cloud blobs) ---
    # Scale 2.5 in normalised Object coords (box is 1×1×1 after apply) → ~2–3 blob
    # widths across the domain → gaps between cloud masses at coverage < 0.5.
    shape_noise = nt.nodes.new("ShaderNodeTexNoise")
    shape_noise.location = (-900, 200)
    shape_noise.inputs["Scale"].default_value = 2.5
    shape_noise.inputs["Detail"].default_value = 2.0
    shape_noise.inputs["Roughness"].default_value = 0.6
    shape_noise.inputs["Distortion"].default_value = 0.2
    links.new(_out(add_wind, "Vector"), shape_noise.inputs["Vector"])

    # --- Fine-detail noise (fluffy edges) ---
    detail_noise = nt.nodes.new("ShaderNodeTexNoise")
    detail_noise.location = (-900, -200)
    detail_noise.inputs["Scale"].default_value = 8.0
    detail_noise.inputs["Detail"].default_value = 4.0
    detail_noise.inputs["Roughness"].default_value = 0.7
    links.new(_out(add_wind, "Vector"), detail_noise.inputs["Vector"])

    # Mix the two noise layers; detail weight controlled by `detail` param.
    mix_noise = _new_mix_rgb(nt)
    mix_noise.location = (-600, 0)
    try:
        mix_noise.blend_type = "MIX"
    except AttributeError:
        pass
    _mix_set_fac(mix_noise, detail)
    links.new(_out(shape_noise, "Fac"), _mix_inp_a(mix_noise))
    links.new(_out(detail_noise, "Fac"), _mix_inp_b(mix_noise))

    # --- Coverage threshold: map combined noise → 0/1 mask with gap ---
    # threshold = 1.0 - coverage (higher coverage → lower threshold → more cloud).
    threshold = max(0.0, min(0.95, 1.0 - coverage))
    coverage_map = nt.nodes.new("ShaderNodeMapRange")
    coverage_map.location = (-300, 0)
    coverage_map.inputs[1].default_value = threshold               # From Min
    coverage_map.inputs[2].default_value = min(1.0, threshold + 0.15)  # From Max
    coverage_map.inputs[3].default_value = 0.0                    # To Min
    coverage_map.inputs[4].default_value = 1.0                    # To Max
    links.new(_mix_out_color(mix_noise), coverage_map.inputs[0])  # Value input

    # --- Vertical falloff: soft bottom, slightly capped top ---
    sep_z = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_z.location = (-1200, -400)
    links.new(tex_coord.outputs["Object"], sep_z.inputs["Vector"])

    # Shift Z from [-0.5, +0.5] to [0, 1].
    add_half = nt.nodes.new("ShaderNodeMath")
    add_half.operation = "ADD"
    add_half.location = (-1000, -400)
    add_half.inputs[1].default_value = 0.5
    links.new(sep_z.outputs["Z"], add_half.inputs[0])

    # Soft bottom ramp: 0→0.2 → 0→1.
    bottom_map = nt.nodes.new("ShaderNodeMapRange")
    bottom_map.location = (-800, -300)
    bottom_map.inputs[1].default_value = 0.0   # From Min
    bottom_map.inputs[2].default_value = 0.2   # From Max
    bottom_map.inputs[3].default_value = 0.0   # To Min
    bottom_map.inputs[4].default_value = 1.0   # To Max
    links.new(add_half.outputs[0], bottom_map.inputs[0])

    # Slight anvil flattening near top: 0.75→1.0 → 1→0.4.
    top_map = nt.nodes.new("ShaderNodeMapRange")
    top_map.location = (-800, -500)
    top_map.inputs[1].default_value = 0.75  # From Min
    top_map.inputs[2].default_value = 1.0   # From Max
    top_map.inputs[3].default_value = 1.0   # To Min
    top_map.inputs[4].default_value = 0.4   # To Max
    links.new(add_half.outputs[0], top_map.inputs[0])

    # Combine: bottom_ramp * top_ramp = vertical envelope.
    vert_mul = nt.nodes.new("ShaderNodeMath")
    vert_mul.operation = "MULTIPLY"
    vert_mul.location = (-550, -400)
    links.new(bottom_map.outputs[0], vert_mul.inputs[0])
    links.new(top_map.outputs[0], vert_mul.inputs[1])

    # --- Final density = coverage_mask * vertical_envelope * density scalar ---
    mul_vert = nt.nodes.new("ShaderNodeMath")
    mul_vert.operation = "MULTIPLY"
    mul_vert.location = (100, -100)
    links.new(coverage_map.outputs[0], mul_vert.inputs[0])
    links.new(vert_mul.outputs[0], mul_vert.inputs[1])

    mul_density = nt.nodes.new("ShaderNodeMath")
    mul_density.operation = "MULTIPLY"
    mul_density.location = (300, -100)
    mul_density.inputs[1].default_value = density
    links.new(mul_vert.outputs[0], mul_density.inputs[0])

    links.new(mul_density.outputs[0], principled_vol.inputs["Density"])

    return mat


def _make_cirrus_material(bpy, wind_dir_deg: float) -> Any:
    import math

    mat_name = "CloudCirrus_Vol"
    if mat_name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[mat_name])

    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    links = nt.links

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (800, 0)

    pvol = nt.nodes.new("ShaderNodeVolumePrincipled")
    pvol.location = (550, 0)
    pvol.inputs["Anisotropy"].default_value = 0.3
    links.new(pvol.outputs["Volume"], out.inputs["Volume"])

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-900, 0)

    wind_rad = math.radians(wind_dir_deg)
    wind_x = math.cos(wind_rad) * 800.0
    wind_y = math.sin(wind_rad) * 800.0
    add_wind = nt.nodes.new("ShaderNodeVectorMath")
    add_wind.operation = "ADD"
    add_wind.location = (-700, 0)
    add_wind.inputs[1].default_value = (wind_x, wind_y, 0.0)
    links.new(tex_coord.outputs["Object"], add_wind.inputs[0])

    # Stretched noise: compress Y → wispy streaks along X.
    stretch = nt.nodes.new("ShaderNodeVectorMath")
    stretch.operation = "MULTIPLY"
    stretch.location = (-500, 0)
    stretch.inputs[1].default_value = (1.0, 0.12, 1.0)
    links.new(_out(add_wind, "Vector"), stretch.inputs[0])

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-250, 0)
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = 0.5
    links.new(_out(stretch, "Vector"), noise.inputs["Vector"])

    # Very low density threshold; cirrus is faint.
    cov_map = nt.nodes.new("ShaderNodeMapRange")
    cov_map.location = (50, 0)
    cov_map.inputs[1].default_value = 0.55  # From Min
    cov_map.inputs[2].default_value = 0.75  # From Max
    cov_map.inputs[3].default_value = 0.0   # To Min
    cov_map.inputs[4].default_value = 1.0   # To Max
    links.new(_out(noise, "Fac"), cov_map.inputs[0])

    mul_d = nt.nodes.new("ShaderNodeMath")
    mul_d.operation = "MULTIPLY"
    mul_d.location = (270, 0)
    mul_d.inputs[1].default_value = 0.008  # very faint
    links.new(cov_map.outputs[0], mul_d.inputs[0])
    links.new(mul_d.outputs[0], pvol.inputs["Density"])

    return mat


# ---------------------------------------------------------------------------
# Render efficiency
# ---------------------------------------------------------------------------

def _tune_volume_step_rate(bpy) -> None:
    """Set a sane volume step rate so renders don't crawl.

    Blender's default step rate of 1.0 is very fine for small volumes. For a
    large 20-km cloud deck a step rate of 5–8 (Cycles) gives acceptable quality
    at 5–10× the speed. Eevee Next has its own volume tile size / samples which
    we leave at defaults (they're already conservative).
    """
    try:
        scene = bpy.context.scene
        if hasattr(scene, "cycles"):
            scene.cycles.volume_step_rate = 5.0
            scene.cycles.volume_max_steps = 256
    except Exception:
        pass
