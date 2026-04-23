"""Smoke-probe: import every bpy-dependent module inside real Blender
and report what works vs. what raises. Run via:

    blender --background --python research_bot/blender_tools/tests/smoke_bpy_probe.py

Must be invoked from the repo root so the relative sys.path insert works.
"""
import sys
import os
import traceback

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PKG_PARENT = os.path.join(REPO_ROOT, "research_bot")
sys.path.insert(0, PKG_PARENT)

print("=" * 60)
print("Python:", sys.version_info[:3])
try:
    import bpy
    print("Blender bpy:", bpy.app.version)
except Exception as e:
    print("bpy import failed:", e)
print("sys.path[0]:", sys.path[0])
print("=" * 60)

MODULES = [
    "blender_tools",
    "blender_tools.cli",
    "blender_tools.geo_import",
    "blender_tools.waypoints_to_camera",
    "blender_tools.step_retessellate",
    "blender_tools.cleanup_pymeshlab",
    "blender_tools.hidden_geo_cull",
    "blender_tools.ndvi_scatter",
    "blender_tools.terrain_setup",
    "blender_tools.citygml_import",
    "blender_tools.world_setup",
]

ok, bad = [], []
for name in MODULES:
    try:
        __import__(name)
        print("OK   :", name)
        ok.append(name)
    except Exception as e:
        tb = traceback.format_exc().splitlines()
        last = tb[-1] if tb else str(e)
        first_frame = next((l for l in tb if REPO_ROOT.replace("\\", "/") in l.replace("\\", "/") or "blender_tools" in l), "")
        print("FAIL :", name, "|", last)
        if first_frame:
            print("       at:", first_frame.strip())
        bad.append((name, last))

print("=" * 60)
print(f"SUMMARY: {len(ok)} ok, {len(bad)} failed")
for name, err in bad:
    print(" -", name, "→", err)
