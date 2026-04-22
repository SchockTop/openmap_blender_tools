"""pymeshlab filter-chain wrapper for CAD mesh hygiene.

Used after retessellation (or on direct STL input) to fix the predictable
pathologies: duplicate vertices, T-junctions, zero-area faces, flipped
normals, non-manifold edges.

Pure-Python helpers (default_filter_chain, validate_filter_chain) are
pymeshlab-free; the execute function needs pymeshlab installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# Canonical filter sequence per raw/CADtoBLEND §6.
_DEFAULT_FILTER_CHAIN: list[tuple[str, dict]] = [
    ("meshing_remove_duplicate_vertices", {}),
    ("meshing_merge_close_vertices", {"threshold": {"percentage": 0.01}}),
    ("meshing_remove_null_faces", {}),
    ("meshing_remove_duplicate_faces", {}),
    ("meshing_remove_t_vertices", {"method": "Edge Flip", "threshold": 40}),
    ("meshing_repair_non_manifold_edges", {}),
    ("meshing_re_orient_faces_coherently", {}),
]

# Valid method names (whitelist for validation).
_VALID_T_VERTEX_METHODS = {"Edge Flip", "Edge Collapse"}


def default_filter_chain() -> list[tuple[str, dict]]:
    """Return a deep copy of the canonical filter chain for CAD hygiene."""
    import copy
    return copy.deepcopy(_DEFAULT_FILTER_CHAIN)


def validate_filter_chain(chain: list[tuple[str, dict]]) -> None:
    """Validate a filter chain for obvious mistakes; raises ValueError.

    Rules:
    - Every entry must be a 2-tuple (filter_name, params_dict).
    - filter_name must start with 'meshing_' (pymeshlab convention) or be
      in an allowed non-meshing list (empty for now).
    - T-vertex method, if specified, must be in _VALID_T_VERTEX_METHODS.
    - No filter may appear twice in the chain (catches accidental duplication).
    """
    if not isinstance(chain, list):
        raise ValueError(f"filter_chain must be a list, got {type(chain).__name__}")
    seen: set[str] = set()
    for i, entry in enumerate(chain):
        if not (isinstance(entry, tuple) and len(entry) == 2):
            raise ValueError(
                f"chain[{i}] must be a (name, params) tuple, got {entry!r}"
            )
        name, params = entry
        if not isinstance(name, str) or not name.startswith("meshing_"):
            raise ValueError(
                f"chain[{i}]: filter name must start with 'meshing_', got {name!r}"
            )
        if not isinstance(params, dict):
            raise ValueError(
                f"chain[{i}]: params must be a dict, got {type(params).__name__}"
            )
        if name in seen:
            raise ValueError(f"chain[{i}]: filter {name!r} appears twice")
        seen.add(name)
        if name == "meshing_remove_t_vertices":
            method = params.get("method")
            if method is not None and method not in _VALID_T_VERTEX_METHODS:
                raise ValueError(
                    f"chain[{i}]: T-vertex method {method!r} invalid. "
                    f"Valid: {sorted(_VALID_T_VERTEX_METHODS)}"
                )


def _require_pymeshlab() -> Any:
    try:
        import pymeshlab  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "cleanup_pymeshlab requires pymeshlab. "
            "Install via pip install -e '.[cad]' in research_bot/blender_tools."
        ) from e
    return pymeshlab


def clean_cad_mesh(
    input_mesh: Path,
    output_mesh: Path,
    filter_chain: list[tuple[str, dict]] | None = None,
) -> Path:
    """Apply the filter chain to input_mesh, write output_mesh.

    Returns output_mesh path. Supports .obj / .ply / .stl / .glb / .gltf
    (anything pymeshlab's MeshSet.save_current_mesh handles).
    """
    chain = filter_chain if filter_chain is not None else default_filter_chain()
    validate_filter_chain(chain)

    pml = _require_pymeshlab()
    ms = pml.MeshSet()
    ms.load_new_mesh(str(input_mesh))
    for filter_name, params in chain:
        # apply_filter takes kwargs; pymeshlab 2023.12+ signature.
        ms.apply_filter(filter_name, **params)
    ms.save_current_mesh(str(output_mesh))
    return output_mesh
