"""Smoke-probe: actually CALL bpy-dependent functions and report API
mismatches against the installed Blender.

Run from repo root:
    blender --background --python research_bot/blender_tools/tests/smoke_bpy_calls.py
"""
import sys, os, site, traceback

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "research_bot"))
# Blender --background disables user-site; re-enable so wheels we installed via
# pip for Blender's Python (pyproj, numpy) become importable.
_user_site = site.getusersitepackages()
if _user_site and os.path.isdir(_user_site) and _user_site not in sys.path:
    sys.path.insert(0, _user_site)

import bpy
print("=" * 60)
print("bpy.app.version:", bpy.app.version)
print("=" * 60)

results = []
def probe(label, fn):
    try:
        fn()
        print(f"OK    {label}")
        results.append((label, "ok", ""))
    except Exception as e:
        tb = traceback.format_exc().splitlines()
        key = f"{type(e).__name__}: {e}"
        print(f"FAIL  {label}")
        print(f"      {key}")
        # Show first blender_tools frame for location
        for line in tb:
            if "blender_tools" in line and ".py" in line:
                print(f"      at: {line.strip()}")
                break
        results.append((label, "fail", key))

# -- world_setup ------------------------------------------------------
from blender_tools import world_setup

def call_world_sky_default():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    world_setup.setup_multiple_scattering_sky(preset="client-default")

def call_world_sky_airbus():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    world_setup.setup_multiple_scattering_sky(preset="airbus-clean")

def call_world_domain_cube():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    world_setup.add_domain_cube_volume((100.0, 100.0, 100.0), preset="client-default")

probe("world_setup.setup_multiple_scattering_sky(client-default)", call_world_sky_default)
probe("world_setup.setup_multiple_scattering_sky(airbus-clean)", call_world_sky_airbus)
probe("world_setup.add_domain_cube_volume", call_world_domain_cube)

# -- terrain_setup ----------------------------------------------------
from blender_tools import terrain_setup
# Find public functions
public = [n for n in dir(terrain_setup) if not n.startswith("_") and callable(getattr(terrain_setup, n))]
print("terrain_setup public:", public)

# -- waypoints_to_camera ---------------------------------------------
from blender_tools import waypoints_to_camera
public_wpt = [n for n in dir(waypoints_to_camera) if not n.startswith("_") and callable(getattr(waypoints_to_camera, n))]
print("waypoints_to_camera public:", public_wpt)

# -- hidden_geo_cull --------------------------------------------------
from blender_tools import hidden_geo_cull
public_hg = [n for n in dir(hidden_geo_cull) if not n.startswith("_") and callable(getattr(hidden_geo_cull, n))]
print("hidden_geo_cull public:", public_hg)

# -- citygml_import ---------------------------------------------------
from blender_tools import citygml_import
public_cg = [n for n in dir(citygml_import) if not n.startswith("_") and callable(getattr(citygml_import, n))]
print("citygml_import public:", public_cg)

# -- waypoints end-to-end -------------------------------------------
import tempfile, textwrap
csv_text = textwrap.dedent("""\
    lat,lon,alt
    48.1371,11.5754,520
    48.1400,11.5800,540
    48.1450,11.5900,560
""")
tmpdir = tempfile.mkdtemp()
csv_path = os.path.join(tmpdir, "wp.csv")
with open(csv_path, "w", encoding="utf-8") as f:
    f.write(csv_text)

curve_obj_holder = {}
def call_waypoints_bezier():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    curve = waypoints_to_camera.wgs84_csv_to_bezier(csv_path)
    curve_obj_holder["curve"] = curve
def call_waypoints_rig():
    waypoints_to_camera.attach_camera_rig(curve_obj_holder["curve"])

probe("waypoints_to_camera.wgs84_csv_to_bezier", call_waypoints_bezier)
probe("waypoints_to_camera.attach_camera_rig", call_waypoints_rig)

# -- hidden_geo_cull --------------------------------------------------
def call_hidden_name_pattern():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.active_object.name = "_hidden_bolt_01"
    bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
    bpy.context.active_object.name = "Rocket_Body"
    n = hidden_geo_cull.cull_by_name_pattern(patterns=["_hidden_.*"])
    print(f"       → culled {n} object(s)")

probe("hidden_geo_cull.cull_by_name_pattern", call_hidden_name_pattern)

# -- terrain_setup (pure helper + real build) -----------------------
def call_terrain_pure():
    x, y, verts = terrain_setup.compute_plane_dimensions((1000.0, 500.0), 8)
    assert (x, y, verts) == (1000.0, 500.0, 257), (x, y, verts)

probe("terrain_setup.compute_plane_dimensions", call_terrain_pure)

# Real build needs a heightmap EXR. Try with a tiny one if OpenEXR is available.
def call_terrain_build():
    import numpy as np
    try:
        import OpenEXR, Imath  # noqa: F401
    except ImportError:
        raise RuntimeError("skipped: OpenEXR not installed in Blender's python")
    raise RuntimeError("skipped: writing EXR requires extra deps; not bothering in smoke")

probe("terrain_setup.build_terrain_from_heightmap (skipped)", call_terrain_build)

print("=" * 60)
ok = sum(1 for _, s, _ in results if s == "ok")
fail = sum(1 for _, s, _ in results if s == "fail")
print(f"SUMMARY: {ok} ok, {fail} failed")
