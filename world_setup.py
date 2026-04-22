"""Blender 5.x World + atmosphere + clouds setup.

Three entry points — all require Blender (bpy):

- setup_multiple_scattering_sky: replaces the deprecated Nishita model.
- add_domain_cube_volume: volumetric-haze domain cube around the flight path.
- load_vdb_cloud: loads a JangaFX-style VDB cloud volume.

Pure-Python helpers (deg_to_rad, ev_to_exposure_multiplier, bbox_to_domain_cube_scale)
are bpy-free and fully unit-tested.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


# Pure-Python helpers

def deg_to_rad(deg: float) -> float:
    """Convert degrees to radians."""
    return deg * math.pi / 180.0


def ev_to_exposure_multiplier(ev_stops: float) -> float:
    """Convert EV stops to a linear exposure multiplier.

    EV 0 → 1.0; EV +1 → 2.0; EV -1 → 0.5; EV -8 → 1/256.
    Blender's Render Properties → Color Management → Exposure field takes
    EV stops directly, so this helper is for callers that want a linear
    multiplier instead.
    """
    return 2.0 ** ev_stops


def bbox_to_domain_cube_scale(
    bbox_meters: tuple[float, float, float],
    padding_fraction: float = 0.1,
) -> tuple[float, float, float]:
    """Convert a bounding-box size in meters to Blender cube scale factors.

    Blender's primitive_cube_add creates a default cube with size=2 m (from
    -1 to +1 on each axis). To make the cube cover a bbox of (X, Y, Z) meters
    we set scale = (X/2, Y/2, Z/2). Padding widens the cube by the requested
    fraction on every axis.
    """
    if padding_fraction < 0:
        raise ValueError(f"padding_fraction must be >= 0, got {padding_fraction}")
    x, y, z = bbox_meters
    if x <= 0 or y <= 0 or z <= 0:
        raise ValueError(f"bbox dimensions must be positive, got {bbox_meters}")
    pad = 1.0 + padding_fraction
    return (x / 2.0 * pad, y / 2.0 * pad, z / 2.0 * pad)


def sky_preset_values(preset: str) -> dict[str, float]:
    """Return a dict of Multiple Scattering sky parameters for a named preset.

    Presets:
      airbus-clean  — corporate, cool-neutral, 6500-7500 K equivalent, minimal haze.
      client-default — middle ground (Bavarian rocket client), 5800-6200 K.
      spacex-warm   — warmer, heavier haze, long-lens compression style.
    """
    presets = {
        "airbus-clean": {
            "sun_elevation_rad": deg_to_rad(45.0),
            "sun_rotation_rad": deg_to_rad(45.0),
            "intensity": 0.9,
            "air": 0.5,
            "dust": 0.3,
            "ozone": 1.0,
            "exposure_ev": -8.0,
        },
        "client-default": {
            "sun_elevation_rad": deg_to_rad(40.0),
            "sun_rotation_rad": deg_to_rad(45.0),
            "intensity": 0.8,
            "air": 0.7,
            "dust": 0.5,
            "ozone": 1.2,
            "exposure_ev": -8.0,
        },
        "spacex-warm": {
            "sun_elevation_rad": deg_to_rad(25.0),
            "sun_rotation_rad": deg_to_rad(60.0),
            "intensity": 0.8,
            "air": 0.9,
            "dust": 0.8,
            "ozone": 1.3,
            "exposure_ev": -7.0,
        },
    }
    if preset not in presets:
        raise ValueError(
            f"Unknown sky preset '{preset}'. Valid: {sorted(presets)}"
        )
    return presets[preset]


def volume_preset_values(preset: str) -> dict[str, float | tuple]:
    """Haze density + anisotropy + tint for the aerial-perspective domain cube."""
    presets = {
        "airbus-clean":   {"density": 0.0001, "anisotropy": 0.4, "color_rgb": (0.75, 0.82, 0.92)},
        "client-default": {"density": 0.0003, "anisotropy": 0.4, "color_rgb": (0.72, 0.80, 0.90)},
        "spacex-warm":    {"density": 0.0008, "anisotropy": 0.5, "color_rgb": (0.85, 0.78, 0.70)},
    }
    if preset not in presets:
        raise ValueError(f"Unknown volume preset '{preset}'. Valid: {sorted(presets)}")
    return presets[preset]


# bpy-dependent functions

def _require_bpy() -> Any:
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "world_setup requires Blender's bundled Python (bpy). "
            "Run via: blender --background --python <script>.py"
        ) from e
    return bpy


def setup_multiple_scattering_sky(
    preset: str = "client-default",
    sun_elevation_rad: float | None = None,
    sun_rotation_rad: float | None = None,
    intensity: float | None = None,
    air: float | None = None,
    dust: float | None = None,
    ozone: float | None = None,
    exposure_ev: float | None = None,
    world_name: str = "AerospaceSky",
) -> Any:
    """Configure the scene World with the Multiple Scattering (García Liñán) sky.

    Named preset + per-parameter overrides — any kwarg not None overrides the preset.
    """
    bpy = _require_bpy()
    values = sky_preset_values(preset)
    overrides = {
        "sun_elevation_rad": sun_elevation_rad,
        "sun_rotation_rad":  sun_rotation_rad,
        "intensity": intensity,
        "air": air,
        "dust": dust,
        "ozone": ozone,
        "exposure_ev": exposure_ev,
    }
    for k, v in overrides.items():
        if v is not None:
            values[k] = v

    world = bpy.data.worlds.get(world_name)
    if world is None:
        world = bpy.data.worlds.new(world_name)
    world.use_nodes = True
    bpy.context.scene.world = world

    # Node tree: Sky Texture → Background → World Output.
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputWorld")
    bg = nodes.new("ShaderNodeBackground")
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"  # fallback for Blender <5.1
    # 5.1+ preferred type:
    try:
        sky.sky_type = "MULTIPLE_SCATTERING"
    except TypeError:
        pass  # older blender, Nishita remains

    sky.sun_elevation = values["sun_elevation_rad"]
    sky.sun_rotation = values["sun_rotation_rad"]
    sky.sun_intensity = values["intensity"]
    if hasattr(sky, "air_density"):
        sky.air_density = values["air"]
    if hasattr(sky, "dust_density"):
        sky.dust_density = values["dust"]
    if hasattr(sky, "ozone_density"):
        sky.ozone_density = values["ozone"]

    links.new(sky.outputs[0], bg.inputs[0])
    links.new(bg.outputs[0], output.inputs[0])

    # Exposure (View Transform).
    bpy.context.scene.view_settings.exposure = values["exposure_ev"]
    bpy.context.scene.view_settings.view_transform = "AgX"

    return world


def add_domain_cube_volume(
    bbox_meters: tuple[float, float, float],
    preset: str = "client-default",
    density: float | None = None,
    anisotropy: float | None = None,
    color_rgb: tuple[float, float, float] | None = None,
    object_name: str = "AerialHaze",
    padding_fraction: float = 0.1,
) -> Any:
    """Add a cube enclosing the flight path with a Volume Scatter + Absorption shader."""
    bpy = _require_bpy()
    values = volume_preset_values(preset)
    if density is not None:
        values["density"] = density
    if anisotropy is not None:
        values["anisotropy"] = anisotropy
    if color_rgb is not None:
        values["color_rgb"] = color_rgb

    scale = bbox_to_domain_cube_scale(bbox_meters, padding_fraction)
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
    cube = bpy.context.active_object
    cube.name = object_name
    cube.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    mat = bpy.data.materials.new(f"{object_name}_Volume")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    scatter = nodes.new("ShaderNodeVolumeScatter")
    absorb = nodes.new("ShaderNodeVolumeAbsorption")
    mix = nodes.new("ShaderNodeAddShader")
    scatter.inputs["Density"].default_value = values["density"]
    scatter.inputs["Anisotropy"].default_value = values["anisotropy"]
    scatter.inputs["Color"].default_value = (*values["color_rgb"], 1.0)
    absorb.inputs["Density"].default_value = values["density"] / 3.0
    absorb.inputs["Color"].default_value = (*values["color_rgb"], 1.0)
    links.new(scatter.outputs[0], mix.inputs[0])
    links.new(absorb.outputs[0], mix.inputs[1])
    links.new(mix.outputs[0], out.inputs["Volume"])
    cube.data.materials.append(mat)

    return cube


def load_vdb_cloud(
    vdb_path: str | Path,
    position: tuple[float, float, float] = (0.0, 0.0, 2000.0),
    scale: float = 500.0,
    object_name: str | None = None,
) -> Any:
    """Load a .vdb volume file as a Volume object at the given world position."""
    bpy = _require_bpy()
    vdb = Path(vdb_path)
    if not vdb.exists():
        raise FileNotFoundError(f"VDB not found: {vdb}")
    bpy.ops.object.volume_import(filepath=str(vdb.resolve()), files=[{"name": vdb.name}])
    volume = bpy.context.active_object
    if object_name is not None:
        volume.name = object_name
    volume.location = position
    volume.scale = (scale, scale, scale)
    return volume
