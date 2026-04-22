"""Hidden interior geometry culling — the biggest win on CAD assemblies.

Two strategies:
- cull_by_name_pattern: regex match on object names (bolt|nut|washer|...)
  and move matched objects to a hidden collection. Fast first pass.
- cull_by_render_face_id_visibility: render face-ID passes from a sphere
  of sample cameras; any face never hit is eligible for deletion.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DEFAULT_HIDDEN_PATTERNS = [
    r"\bbolt\b", r"\bnut\b", r"\bwasher\b",
    r"\bgasket\b", r"\bwire\b", r"\bthread(?:ed)?\b",
    r"\binternal?\b", r"\binner\b", r"\bcable\b",
]


def compile_hidden_patterns(patterns: list[str] | None = None) -> list[re.Pattern]:
    """Compile a list of regex-string patterns into re.Pattern objects.

    Defaults to _DEFAULT_HIDDEN_PATTERNS. Empty list is allowed (returns [] —
    caller is responsible for handling 'no matches'). All matching is
    case-insensitive.
    """
    if patterns is None:
        patterns = _DEFAULT_HIDDEN_PATTERNS
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def name_matches_any(name: str, compiled_patterns: list[re.Pattern]) -> bool:
    """Return True if any of the compiled patterns matches the given name."""
    return any(p.search(name) for p in compiled_patterns)


def sample_camera_positions_on_sphere(
    n: int,
    radius: float,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[tuple[float, float, float]]:
    """Return n roughly-uniform positions on a sphere (Fibonacci spiral).

    Used to drive render-face-ID culling from a surrounding camera set.
    """
    import math
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if radius <= 0:
        raise ValueError(f"radius must be positive, got {radius}")
    cx, cy, cz = center
    positions: list[tuple[float, float, float]] = []
    golden = math.pi * (3.0 - math.sqrt(5.0))  # ~2.399963
    for i in range(n):
        y = 1.0 - 2.0 * i / (n - 1) if n > 1 else 0.0
        r = math.sqrt(1.0 - y * y)
        theta = golden * i
        x = math.cos(theta) * r
        z = math.sin(theta) * r
        positions.append((cx + x * radius, cy + y * radius, cz + z * radius))
    return positions


def _require_bpy() -> Any:
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "hidden_geo_cull requires Blender's bundled Python (bpy). "
            "Run via: blender --background --python <script>.py"
        ) from e
    return bpy


def cull_by_name_pattern(
    patterns: list[str] | None = None,
    hidden_collection_name: str = "_Hidden",
) -> int:
    """Move every object whose name matches any pattern into a hidden collection.

    Returns the number of objects moved.
    """
    bpy = _require_bpy()
    compiled = compile_hidden_patterns(patterns)

    hidden = bpy.data.collections.get(hidden_collection_name)
    if hidden is None:
        hidden = bpy.data.collections.new(hidden_collection_name)
        bpy.context.scene.collection.children.link(hidden)

    moved = 0
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        if name_matches_any(obj.name, compiled):
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            hidden.objects.link(obj)
            obj.hide_viewport = True
            obj.hide_render = True
            moved += 1
    return moved


def cull_by_render_face_id_visibility(
    n_sample_cameras: int = 20,
    radius_meters: float = 10.0,
    center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> int:
    """Render face-ID passes from sample cameras; delete never-seen faces.

    Implementation is expensive and Blender-specific; this Phase-2 scaffold
    only sets up the sample-camera positions and returns a count of planned
    deletions. Full implementation tracked as follow-up.
    """
    bpy = _require_bpy()  # confirms bpy available
    positions = sample_camera_positions_on_sphere(n_sample_cameras, radius_meters, center)
    # Scaffolded return: 0 deletions (caller is informed the full path is a TODO).
    return 0
