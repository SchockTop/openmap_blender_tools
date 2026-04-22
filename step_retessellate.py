"""STEP AP242 → retessellated glTF via OpenCascade.

Uses pythonocc-core (or cadquery-ocp). Calls BRepMesh_IncrementalMesh with
the chosen chord-deflection parameters, then emits glTF via RWGltf_CafWriter
to preserve the CAF assembly tree + per-face colours + instances.

Pure-Python helpers (tessellation_params_for_quality, orientation_flip_indices,
validate_input_path) are OCCT-free and fully unit-tested.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Named quality presets — picks linear-deflection (mm) + angular (rad).
_QUALITY_PRESETS = {
    "hero":       {"linear_mm": 0.02, "angular_rad": 0.1,  "description": "Cinematic close-up, 6–10 M tris at 16 M-vertex input"},
    "mid":        {"linear_mm": 0.10, "angular_rad": 0.15, "description": "Mid shot, ~1 M tris"},
    "wide":       {"linear_mm": 0.50, "angular_rad": 0.3,  "description": "Wide / orbital, ~150 k tris"},
    "background": {"linear_mm": 1.00, "angular_rad": 0.5,  "description": "Distant / plume, ~10 k tris"},
}


def tessellation_params_for_quality(quality: str) -> dict[str, Any]:
    """Return tessellation params for a named quality preset.

    Raises ValueError for unknown presets. The returned dict has keys
    'linear_mm', 'angular_rad', 'description'.
    """
    if quality not in _QUALITY_PRESETS:
        raise ValueError(
            f"Unknown quality '{quality}'. Valid: {sorted(_QUALITY_PRESETS)}"
        )
    # Return a copy so callers can mutate freely.
    return dict(_QUALITY_PRESETS[quality])


def orientation_flip_indices(
    triangles: list[tuple[int, int, int]],
    is_reversed: bool,
) -> list[tuple[int, int, int]]:
    """Flip triangle winding iff is_reversed is True.

    OpenCascade BRepMesh emits per-face triangulations that must be flipped
    for faces whose topological orientation is TopAbs_REVERSED. Getting this
    wrong is the #1 source of 'inverted normals after STEP → mesh' issues.
    """
    if not is_reversed:
        return list(triangles)
    return [(t[0], t[2], t[1]) for t in triangles]


def validate_input_path(step_path: Path, allow_nonexistent: bool = False) -> Path:
    """Confirm the STEP path exists and has a STEP-ish extension.

    Returns a resolved absolute path. Raises FileNotFoundError / ValueError.
    """
    p = Path(step_path).resolve()
    if not allow_nonexistent and not p.exists():
        raise FileNotFoundError(f"STEP file not found: {p}")
    if p.suffix.lower() not in {".step", ".stp", ".stpz"}:
        raise ValueError(
            f"Expected a .step/.stp file, got {p.suffix!r}: {p}. "
            f"If input is .CATPart, convert via Datakit CrossManager first."
        )
    return p


# OCCT-dependent entry point

def _require_occt() -> Any:
    """Import pythonocc-core or cadquery-ocp."""
    try:
        import OCP  # type: ignore[import-not-found]
        return OCP
    except ImportError:
        pass
    try:
        import OCC  # type: ignore[import-not-found]
        return OCC
    except ImportError as e:
        raise RuntimeError(
            "step_retessellate requires pythonocc-core or cadquery-ocp. "
            "Install via pip install -e '.[cad]' in research_bot/blender_tools."
        ) from e


def retessellate_step_to_gltf(
    step_path: Path,
    output_gltf: Path,
    quality: str = "hero",
    parallel: bool = True,
    clean_model: bool = True,
) -> Path:
    """Read a STEP file, retessellate at the given quality, write glTF.

    Returns the output_gltf path. Preserves CAF assembly tree + face colours.

    NOTE: The RWGltf_CafWriter path requires a TDocStd_Document/CAF document
    that is non-trivial to set up and depends on the installed OCP version.
    For Phase 2 W6, this function raises NotImplementedError to signal the
    scaffold boundary. Full OCCT glTF-write implementation is tracked as a
    follow-up task. As a simpler fallback, use trimesh to export to glTF after
    extracting the BRep mesh manually.
    """
    # Validate inputs first (no OCCT needed).
    step_path = validate_input_path(step_path)
    tessellation_params_for_quality(quality)  # raises ValueError for bad quality
    _require_occt()  # raises RuntimeError if not installed

    raise NotImplementedError(
        "Full RWGltf_CafWriter wiring requires a TDocStd_Document; "
        "scaffolded for follow-up. Use trimesh.write() for a simple glTF as a fallback."
    )
