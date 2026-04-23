"""Functional smoke test for the INSTALLED extension.

Exercises bpy.ops.blender_tools.* operators — the same code path a user hits by
clicking in the Blender UI. Run via:

    blender --background --python research_bot/blender_tools/tests/smoke_extension.py

Requires the extension to be installed & enabled (see build_extension.py).
"""
import sys
import traceback

import bpy

print("=" * 60)
print("bpy.app.version:", bpy.app.version)

ext_name = "bl_ext.user_default.blender_tools"

import importlib

try:
    ext = importlib.import_module(ext_name)
    print(f"extension loaded: {ext.__name__} v{ext.__version__}")
except Exception as e:
    print(f"FAIL  could not import {ext_name}: {e}")
    raise

# Extensions auto-register in 5.1 even in --background when enabled at install.
# No need to call register() manually.

print("=" * 60)

results = []


def probe(label, fn):
    try:
        fn()
        print(f"OK    {label}")
        results.append((label, "ok"))
    except Exception as e:
        tb = traceback.format_exc().splitlines()
        key = f"{type(e).__name__}: {e}"
        print(f"FAIL  {label}")
        print(f"      {key}")
        for line in tb:
            if "blender_tools" in line and ".py" in line:
                print(f"      at: {line.strip()}")
                break
        results.append((label, "fail"))


def op_setup_sky():
    # Clear scene without reloading extensions.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name != "Collection":
            bpy.data.collections.remove(coll)
    r = bpy.ops.blender_tools.setup_sky(preset="client-default")
    assert r == {"FINISHED"}, r
    world = bpy.context.scene.world
    assert world is not None
    sky_node = next(n for n in world.node_tree.nodes if n.type == "TEX_SKY")
    print(f"      sky.sky_type = {sky_node.sky_type!r}")


def op_add_domain_cube():
    # Clear scene without reloading extensions.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name != "Collection":
            bpy.data.collections.remove(coll)
    r = bpy.ops.blender_tools.add_domain_cube(bbox=(500.0, 500.0, 200.0), preset="airbus-clean")
    assert r == {"FINISHED"}, r
    cube = next((o for o in bpy.data.objects if "AerialHaze" in o.name), None)
    assert cube is not None, "AerialHaze cube not found"
    print(f"      cube.scale = {tuple(cube.scale)}")


def op_cull_hidden():
    # Clear scene without reloading extensions.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        if coll.name != "Collection":
            bpy.data.collections.remove(coll)
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.active_object.name = "_hidden_bolt_01"
    bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
    bpy.context.active_object.name = "Rocket_Body"
    r = bpy.ops.blender_tools.cull_hidden(pattern=r"_hidden_.*")
    assert r == {"FINISHED"}, r
    hidden = bpy.data.collections.get("_Hidden")
    assert hidden is not None, "_Hidden collection not created"
    names = [o.name for o in hidden.objects]
    print(f"      _Hidden contents = {names}")
    assert any(n.startswith("_hidden_") for n in names)


# Verify bundled wheels ended up importable (proves the Extension's wheel system worked).
def wheels_importable():
    import pyproj, numpy, trimesh  # noqa: F401
    print(f"      pyproj={pyproj.__version__} numpy={numpy.__version__} trimesh={trimesh.__version__}")


probe("wheels (pyproj/numpy/trimesh) importable from extension site", wheels_importable)
probe("bpy.ops.blender_tools.setup_sky (preset=client-default)", op_setup_sky)
probe("bpy.ops.blender_tools.add_domain_cube (preset=airbus-clean)", op_add_domain_cube)
probe("bpy.ops.blender_tools.cull_hidden (regex _hidden_.*)", op_cull_hidden)

print("=" * 60)
ok = sum(1 for _, s in results if s == "ok")
fail = sum(1 for _, s in results if s == "fail")
print(f"SUMMARY: {ok} ok, {fail} failed")
if fail:
    sys.exit(1)
