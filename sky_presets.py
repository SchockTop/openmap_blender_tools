"""sky_presets.py — named time-of-day lighting moods for the cinematic scene.

Each preset reconfigures the CinematicSun (rotation + energy + color) and the
world Sky background to produce the named mood. Independent from
camera_presets — you can pair any sky_preset with any camera_preset.

The "physically real" presets (noon / golden-hour / blue-hour / dawn) use
real-world sun-angle approximations for München (48.14°N) on a clear day.
The "stylised" presets (overcast) trade physical realism for visual mood.
"""
from __future__ import annotations
import math
from typing import Any


SKY_PRESETS: dict[str, dict[str, Any]] = {
    "noon": {
        "label": "Midday — direct overhead sun, cool white light",
        "sun_pitch_deg": 25.0,         # nearly overhead
        "sun_azimuth_deg": 0.0,         # from south
        "sun_energy": 100.0,
        "sun_color_rgb": (1.0, 0.97, 0.93),
        "sky_strength": 1.0,
        "sky_air_density": 1.0,
        "exposure_offset": 0.5,         # daylight needs minimal compensation
    },
    "golden-hour": {
        "label": "Golden hour (1h before sunset) — warm low sun + long shadows",
        "sun_pitch_deg": 75.0,          # very low (close to horizon)
        "sun_azimuth_deg": 75.0,        # west-southwest
        "sun_energy": 50.0,
        "sun_color_rgb": (1.0, 0.78, 0.55),  # warm orange
        "sky_strength": 1.2,
        "sky_air_density": 2.5,         # extra atmospheric scattering
        "exposure_offset": 0.5,
    },
    "blue-hour": {
        "label": "Blue hour (post-sunset twilight) — cool ambient, no direct sun",
        "sun_pitch_deg": 95.0,          # below horizon (still casts soft fill)
        "sun_azimuth_deg": 75.0,
        "sun_energy": 5.0,              # faint (sun below horizon)
        "sun_color_rgb": (0.5, 0.6, 0.95),
        "sky_strength": 0.8,
        "sky_air_density": 3.5,
        "exposure_offset": 1.5,         # boost exposure for visibility
    },
    "dawn": {
        "label": "Dawn (just after sunrise) — soft low east sun, pinkish",
        "sun_pitch_deg": 80.0,
        "sun_azimuth_deg": -75.0,        # east
        "sun_energy": 40.0,
        "sun_color_rgb": (1.0, 0.85, 0.78),
        "sky_strength": 1.0,
        "sky_air_density": 2.2,
        "exposure_offset": 1.0,
    },
    "overcast": {
        "label": "Overcast — flat diffuse light, no shadows",
        "sun_pitch_deg": 45.0,
        "sun_azimuth_deg": 30.0,
        "sun_energy": 20.0,             # low — overcast filters direct light
        "sun_color_rgb": (0.92, 0.94, 1.0),
        "sky_strength": 2.0,            # bright sky = main light source
        "sky_air_density": 4.0,
        "exposure_offset": 0.5,
    },
    "afternoon": {
        "label": "Afternoon — sun 60° from vertical, southwesterly (default cinematic)",
        "sun_pitch_deg": 60.0,
        "sun_azimuth_deg": 30.0,
        "sun_energy": 10.0,
        "sun_color_rgb": (1.0, 0.95, 0.88),
        "sky_strength": 0.2,
        "sky_air_density": 1.5,
        "exposure_offset": 0.0,
    },
}

DEFAULT_SKY_PRESET = "afternoon"


def list_sky_presets() -> list[str]:
    return list(SKY_PRESETS.keys())


def get_sky_preset(name: str) -> dict[str, Any]:
    if name not in SKY_PRESETS:
        raise KeyError(f"unknown sky preset {name!r}; available: {sorted(SKY_PRESETS)}")
    return SKY_PRESETS[name]


def apply_sky_preset(scene: Any, preset_name: str) -> dict[str, Any]:
    """Apply named sky/lighting preset to the current scene.

    Reconfigures any existing CinematicSun light + the world's Sky background.
    Idempotent. Returns the preset dict.
    """
    p = get_sky_preset(preset_name)

    # Find or warn about CinematicSun.
    sun_obj = next((o for o in scene.objects
                    if o.type == "LIGHT" and getattr(o.data, "type", None) == "SUN"), None)
    if sun_obj is None:
        print(f"[sky-preset] WARN: no Sun light found; create one via cinematic_preset first")
    else:
        sun_obj.data.energy = p["sun_energy"]
        sun_obj.data.color = p["sun_color_rgb"]
        sun_obj.rotation_euler = (math.radians(p["sun_pitch_deg"]),
                                   0.0,
                                   math.radians(p["sun_azimuth_deg"]))

    # Update world sky.
    world = scene.world
    if world is not None and world.use_nodes and world.node_tree:
        for node in world.node_tree.nodes:
            if node.type == "TEX_SKY":
                if hasattr(node, "air_density"):
                    try: node.air_density = p["sky_air_density"]
                    except (AttributeError, TypeError): pass
                # Sun tilt (vector) in sky shader.
                if hasattr(node, "sun_elevation"):
                    try:
                        node.sun_elevation = math.radians(90.0 - p["sun_pitch_deg"])
                        node.sun_rotation = math.radians(p["sun_azimuth_deg"])
                    except (AttributeError, TypeError): pass
            if node.type == "BACKGROUND":
                if "Strength" in node.inputs:
                    node.inputs["Strength"].default_value = p["sky_strength"]

    # Exposure compensation per preset.
    scene.view_settings.exposure = p["exposure_offset"]

    print(f"[sky-preset] applied {preset_name!r}: pitch {p['sun_pitch_deg']}°, "
          f"energy {p['sun_energy']}, exposure {p['exposure_offset']}")
    return p
