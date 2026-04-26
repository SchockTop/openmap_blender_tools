"""End-to-end smoke: build a real scene from waypoints + sky + domain cube + cull,
then save .blend so a human can open it.

Run:
    blender --background --python research_bot/blender_tools/tests/smoke_full_scene.py
"""
import os, tempfile, textwrap, sys, traceback, importlib
import bpy

OUT = os.path.join(tempfile.gettempdir(), "blender_tools_smoke_scene.blend")
print("=" * 60)
print("bpy.app.version:", bpy.app.version)
print("output blend  :", OUT)
print("=" * 60)

# Load extension (do NOT call read_factory_settings — it disables installed extensions).
ext = importlib.import_module("bl_ext.user_default.blender_tools")
print(f"extension loaded: v{ext.__version__}")

# Empty the default scene manually.
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for coll in list(bpy.data.collections):
    if coll.name != "Collection":
        bpy.data.collections.remove(coll)

# 1) Sky + atmosphere
r = bpy.ops.blender_tools.setup_sky(preset="client-default")
assert r == {"FINISHED"}, r
print("OK  sky")

# 2) Domain cube (aerial haze volume)
r = bpy.ops.blender_tools.add_domain_cube(bbox=(800.0, 800.0, 250.0), preset="airbus-clean")
assert r == {"FINISHED"}, r
print("OK  domain cube")

# 3) Waypoint camera from a CSV
csv_text = textwrap.dedent("""\
    lat,lon,alt
    48.1371,11.5754,520
    48.1400,11.5800,540
    48.1450,11.5900,560
    48.1500,11.5950,580
""")
csv_path = os.path.join(tempfile.gettempdir(), "wp_smoke.csv")
with open(csv_path, "w", encoding="utf-8") as f:
    f.write(csv_text)

waypoints_to_camera = importlib.import_module("bl_ext.user_default.blender_tools.waypoints_to_camera")
curve = waypoints_to_camera.wgs84_csv_to_bezier(csv_path)
cam = waypoints_to_camera.attach_camera_rig(curve)
print(f"OK  camera rig along curve ({curve.name}, cam={cam.name})")

# 4) Add some "junk" geometry then cull it
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
bpy.context.active_object.name = "Rocket_Body"
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
bpy.context.active_object.name = "_hidden_bolt_01"
bpy.ops.mesh.primitive_cube_add(location=(-3, 0, 0))
bpy.context.active_object.name = "_hidden_nut_02"
r = bpy.ops.blender_tools.cull_hidden(pattern=r"_hidden_.*")
assert r == {"FINISHED"}, r
hidden = bpy.data.collections.get("_Hidden")
print(f"OK  cull → _Hidden has {len(hidden.objects)} obj(s)")

# 5) Inventory
print("=" * 60)
print("Scene inventory:")
for o in bpy.data.objects:
    print(f"  - {o.type:8s}  {o.name}")
print("Collections:")
for c in bpy.data.collections:
    print(f"  - {c.name}: {[o.name for o in c.objects]}")
print(f"World: {bpy.context.scene.world.name}")

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("=" * 60)
print(f"SAVED: {OUT}")
print("Open with: blender", OUT)
