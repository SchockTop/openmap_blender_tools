"""Feature-registry for modular scene-builder plug-ins.

Each feature is a single Python module exposing two top-level constants and
one function:

    NAME: str          - kebab-case identifier used on the --enable CLI flag
    DESCRIPTION: str   - one-line human description
    def apply(context: dict) -> dict:
        '''Apply the feature to the current Blender scene.

        Args:
            context: dict with at least these keys, populated by the assembler:
                bpy: the bpy module (saves each module re-importing)
                scene: bpy.context.scene
                terrain_obj: the terrain mesh object (or None)
                dop_image: bpy.types.Image of the UDIM ortho (or None)
                ortho_dir: Path to the UDIM ortho dir (or None)
                building_objs: list[bpy.types.Object] from CityJSON (or [])
                bbox_utm32n: (xmin, ymin, xmax, ymax) tuple
                anchor_utm32n: (x, y, z) tuple
                args: argparse.Namespace from the CLI

        Returns:
            dict of feature-specific outputs to merge into context for later
            features. Empty dict if nothing to publish.
        '''

Modules that import bpy at module-load are fine — they'll only be loaded by
the assembler (running inside Blender). The registry itself is bpy-free so it
can be unit-tested in plain CPython.
"""
from __future__ import annotations
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any


def discover() -> dict[str, Any]:
    """Find every *.py module next to this __init__.py that exposes NAME + apply.

    Returns {NAME: module} mapping. Modules that fail to import (e.g., missing
    dependency) are skipped with a printed warning, not raised.
    """
    here = Path(__file__).resolve().parent
    found: dict[str, Any] = {}
    for py in sorted(here.glob("*.py")):
        if py.name in {"__init__.py"}:
            continue
        mod_name = f"{__name__}.{py.stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            print(f"[features] skip {py.stem}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            continue
        if not (hasattr(mod, "NAME") and hasattr(mod, "apply")):
            continue
        found[mod.NAME] = mod
    return found


def apply_enabled(enabled: list[str], context: dict[str, Any]) -> dict[str, Any]:
    """Apply each enabled feature in the order given.

    Each feature's outputs are merged into the context before the next runs,
    so later features can consume earlier features' results (e.g., trees
    needs ground_shader's NDVI mask).
    """
    available = discover()
    for name in enabled:
        mod = available.get(name)
        if mod is None:
            print(f"[features] '{name}' not available; skipping", file=sys.stderr)
            continue
        try:
            print(f"[features] apply {name}: {mod.DESCRIPTION}")
            outputs = mod.apply(context) or {}
            context.update(outputs)
        except Exception as e:
            import traceback
            print(f"[features] FAIL {name}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            traceback.print_exc()
            # Continue with the rest of the features.
    return context
