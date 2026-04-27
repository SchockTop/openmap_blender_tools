"""cinematic_preset.py — one-call scene tuning for cinematic LDBV renders.

Sets defaults that the Thread-4 cinematic playbooks document but that
Blender does not turn on automatically: long camera clip range, viewport
simplify, render engine + sample budget, AgX view transform, volumetric
shadows. Idempotent — safe to call multiple times.
"""
from __future__ import annotations
import math
from typing import Any


def _require_bpy() -> Any:
    try:
        import bpy  # type: ignore[import-not-found]
        return bpy
    except ImportError as e:
        raise RuntimeError(
            "cinematic_preset requires Blender's bundled Python (bpy)."
        ) from e


def _ensure_cinematic_sun(scene: Any,
                          name: str = "CinematicSun",
                          energy: float = 150.0,
                          pitch_deg: float = 60.0,
                          azimuth_deg: float = 30.0) -> Any:
    """Add a Sun light to the scene if none exists.

    A Multiple-Scattering Sky alone provides only ambient illumination — without
    a directional Sun, ground-plane renders come out near-black. This helper is
    idempotent: skips creation if any SUN-type light is already present.
    """
    bpy = _require_bpy()
    # Idempotent: skip if any SUN already exists.
    for obj in scene.objects:
        if obj.type == "LIGHT" and obj.data.type == "SUN":
            return obj
    light_data = bpy.data.lights.new(name=name + "Data", type="SUN")
    light_data.energy = energy
    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    light_obj.location = (0.0, 0.0, 10000.0)
    light_obj.rotation_euler = (math.radians(pitch_deg), 0.0,
                                math.radians(azimuth_deg))
    scene.collection.objects.link(light_obj)
    return light_obj


def set_camera_clip_for_large_scene(camera_data: Any,
                                    clip_start: float = 1.0,
                                    clip_end: float = 100_000.0) -> None:
    """Set Camera clip range so 10-km terrain doesn't cull at the horizon."""
    camera_data.clip_start = clip_start
    camera_data.clip_end = clip_end


def apply_cinematic_preset(scene: Any,
                           *,
                           render_engine: str = "BLENDER_EEVEE_NEXT",
                           samples: int | None = None,
                           resolution: tuple[int, int] = (1920, 1080),
                           viewport_simplify_subdiv: int = 5,
                           quality: str | None = None) -> None:
    """Apply cinematic-grade scene settings.

    Args:
        scene: bpy.context.scene.
        render_engine: "BLENDER_EEVEE_NEXT" (fast) or "CYCLES" (path-traced).
        samples: render samples; defaults to 64 for Eevee, 256 for Cycles.
        resolution: (x, y) pixel dimensions.
        viewport_simplify_subdiv: cap Subsurf in viewport (full subdiv at render).
        quality: optional quality preset name ("draft" / "preview" / "final"). If
            provided, `quality_presets.apply_quality` is called AFTER the cinematic
            setup so quality wins over the cinematic resolution/sample defaults.
    """
    _ = _require_bpy()  # ensure we're inside Blender; bpy not used directly here

    # Blender 5.x renamed "BLENDER_EEVEE_NEXT" back to "BLENDER_EEVEE" (Eevee
    # Next is the only Eevee in 5.x). Map both spellings to whatever the host
    # actually exposes.
    try:
        valid_engines = {
            i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items
        }
    except Exception:
        valid_engines = {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"}
    if render_engine not in valid_engines:
        if render_engine == "BLENDER_EEVEE_NEXT" and "BLENDER_EEVEE" in valid_engines:
            render_engine = "BLENDER_EEVEE"
        elif render_engine == "BLENDER_EEVEE" and "BLENDER_EEVEE_NEXT" in valid_engines:
            render_engine = "BLENDER_EEVEE_NEXT"
    scene.render.engine = render_engine
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.use_simplify = True
    scene.render.simplify_subdivision = viewport_simplify_subdiv

    if render_engine == "CYCLES":
        scene.cycles.samples = samples if samples is not None else 256
        scene.cycles.use_denoising = True
        try:
            scene.cycles.use_persistent_data = True
        except AttributeError:
            pass
    else:  # Eevee Next
        scene.eevee.taa_render_samples = samples if samples is not None else 64
        scene.eevee.use_volumetric_shadows = True

    # Ensure a directional Sun exists — sky-only scenes render black.
    _ensure_cinematic_sun(scene)

    # AgX (Blender 5.x default but explicit for repro).
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"

    # Exposure compensation — AgX is conservative on highlights, so bump
    # the scene exposure +1.5 stops for a brighter cinematic look.
    scene.view_settings.exposure = 1.5

    # Dial up the world Multiple Scattering Sky strength if present.
    world = scene.world
    if world is not None and world.use_nodes and world.node_tree:
        for node in world.node_tree.nodes:
            if node.type == "TEX_SKY":
                # Sky background: more atmospheric scattering, brighter sun disk.
                if hasattr(node, "air_density"):
                    try:
                        node.air_density = 1.5
                    except (AttributeError, TypeError):
                        pass
            if node.type == "BACKGROUND":
                # Bump sky background strength (scene illumination from sky).
                if "Strength" in node.inputs:
                    node.inputs["Strength"].default_value = max(
                        float(node.inputs["Strength"].default_value), 1.5
                    )

    # Quality envelope (optional) — applied LAST so it overrides resolution/samples
    # set above. Imported lazily to avoid a hard dep when quality is not used.
    if quality is not None:
        from . import quality_presets
        quality_presets.apply_quality(scene, quality)
