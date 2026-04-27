"""quality_presets.py — render-quality envelopes (draft / preview / final).

A single named knob that sets resolution + samples + Subsurf simplify caps +
optionally requests features be skipped (e.g. drop expensive groundcover at
draft quality).

Usage from a Blender script:
    from blender_tools import quality_presets
    quality_presets.apply_quality(bpy.context.scene, "draft")

Usage at the orchestrator level: read
    quality_presets.QUALITY_PRESETS[name]["skip_features"]
to filter the --enable list before invoking the pipeline.

Idempotent — safe to re-apply.
"""
from __future__ import annotations
from typing import Any

QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "draft": {
        "resolution": (480, 270),
        "eevee_taa_render_samples": 8,
        "cycles_samples": 16,
        "viewport_simplify_subdiv": 3,
        "render_simplify_subdiv": 5,
        "skip_features": ["groundcover"],
    },
    "preview": {
        "resolution": (960, 540),
        "eevee_taa_render_samples": 32,
        "cycles_samples": 64,
        "viewport_simplify_subdiv": 5,
        "render_simplify_subdiv": 8,
        "skip_features": [],
    },
    "final": {
        "resolution": (1920, 1080),
        "eevee_taa_render_samples": 128,
        "cycles_samples": 256,
        "viewport_simplify_subdiv": 5,
        "render_simplify_subdiv": 11,
        "skip_features": [],
    },
}


def get_preset(name: str) -> dict[str, Any]:
    """Return the preset dict for `name` or raise KeyError with helpful message."""
    if name not in QUALITY_PRESETS:
        raise KeyError(
            f"Unknown quality preset {name!r}. "
            f"Valid options: {sorted(QUALITY_PRESETS)}"
        )
    return QUALITY_PRESETS[name]


def apply_quality(scene: Any, name: str) -> dict[str, Any]:
    """Apply a quality preset to `scene` and return the preset dict.

    Sets resolution, render-engine-specific samples (both Eevee + Cycles
    so it works regardless of which engine is active), and the Subsurf
    simplify caps. Should be called AFTER `apply_cinematic_preset` so that
    quality wins over the cinematic defaults.
    """
    preset = get_preset(name)
    res_x, res_y = preset["resolution"]
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y

    # Apply samples to whichever engine is active; set both anyway so a later
    # engine swap respects the preset.
    try:
        scene.eevee.taa_render_samples = preset["eevee_taa_render_samples"]
    except AttributeError:
        pass
    try:
        scene.cycles.samples = preset["cycles_samples"]
    except AttributeError:
        pass

    # Subsurf simplify — viewport cap for interactive perf, render cap for
    # final-frame detail.
    scene.render.use_simplify = True
    scene.render.simplify_subdivision = preset["viewport_simplify_subdiv"]
    try:
        scene.render.simplify_subdivision_render = preset["render_simplify_subdiv"]
    except AttributeError:
        pass

    return preset
