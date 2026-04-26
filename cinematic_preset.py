"""cinematic_preset.py — one-call scene tuning for cinematic LDBV renders.

Sets defaults that the Thread-4 cinematic playbooks document but that
Blender does not turn on automatically: long camera clip range, viewport
simplify, render engine + sample budget, AgX view transform, volumetric
shadows. Idempotent — safe to call multiple times.
"""
from __future__ import annotations
from typing import Any


def _require_bpy() -> Any:
    try:
        import bpy  # type: ignore[import-not-found]
        return bpy
    except ImportError as e:
        raise RuntimeError(
            "cinematic_preset requires Blender's bundled Python (bpy)."
        ) from e


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
                           viewport_simplify_subdiv: int = 5) -> None:
    """Apply cinematic-grade scene settings.

    Args:
        scene: bpy.context.scene.
        render_engine: "BLENDER_EEVEE_NEXT" (fast) or "CYCLES" (path-traced).
        samples: render samples; defaults to 64 for Eevee, 256 for Cycles.
        resolution: (x, y) pixel dimensions.
        viewport_simplify_subdiv: cap Subsurf in viewport (full subdiv at render).
    """
    _ = _require_bpy()  # ensure we're inside Blender; bpy not used directly here

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

    # AgX (Blender 5.x default but explicit for repro).
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
