"""Headless smoke test for features/clouds.py.

Run: blender --background --python tests/smoke_clouds.py

Verifies:
- clouds.apply() creates Clouds_Cumulus in the scene.
- Clouds_Cumulus has a volume material.
- A 64×64 Eevee Next render completes without error.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import bpy

# Make the package importable as `blender_tools` from an uninstalled source tree.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO.parent) not in sys.path:
    sys.path.insert(0, str(_REPO.parent))

try:
    import blender_tools  # noqa: F401
except ModuleNotFoundError:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "blender_tools",
        str(_REPO / "__init__.py"),
        submodule_search_locations=[str(_REPO)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blender_tools"] = mod
    spec.loader.exec_module(mod)


def main() -> None:
    from blender_tools.features import clouds

    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Minimal ground plane so the terrain-size fallback has something to measure.
    bpy.ops.mesh.primitive_plane_add(size=5000.0, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "Terrain"

    # Seed the anchor (X/Y only — Z stays 0 because clouds use absolute altitude).
    bpy.context.scene["utm32n_anchor"] = [670000.0, 5255000.0, 0.0]
    bpy.context.scene["bbox_utm32n"] = [670000.0, 5255000.0, 675000.0, 5260000.0]

    ctx = {
        "bpy": bpy,
        "scene": bpy.context.scene,
        "terrain_obj": plane,
        "bbox_utm32n": [670000.0, 5255000.0, 675000.0, 5260000.0],
    }

    result = clouds.apply(ctx, coverage=0.45, cirrus=True)

    assert "cumulus_object" in result, "apply() must return cumulus_object key"
    cumulus_name = result["cumulus_object"]
    assert cumulus_name in bpy.data.objects, f"'{cumulus_name}' not in scene objects"

    cumulus = bpy.data.objects[cumulus_name]
    assert len(cumulus.data.materials) > 0, "Clouds_Cumulus has no material"
    mat = cumulus.data.materials[0]
    assert mat is not None, "material slot is empty"
    # use_nodes is deprecated in Blender 5.x but still settable; node_tree
    # existing is the reliable check.
    assert mat.node_tree is not None, "cloud material must have a node tree"

    assert "cirrus_object" in result, "apply() with cirrus=True must return cirrus_object key"
    cirrus_name = result["cirrus_object"]
    assert cirrus_name in bpy.data.objects, f"'{cirrus_name}' not in scene objects"

    # Tiny render to confirm no shader/node errors at render time.
    scene = bpy.context.scene
    # Blender 5.1 uses "BLENDER_EEVEE" for the Eevee Next engine; earlier
    # builds used "BLENDER_EEVEE_NEXT". Try the new name first.
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = eng
            break
        except TypeError:
            continue
    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
    try:
        scene.eevee.taa_render_samples = 4
    except AttributeError:
        pass

    # Need a camera for rendering.
    bpy.ops.object.camera_add(location=(0, -10000, 5000))
    cam = bpy.context.active_object
    cam.rotation_euler = (1.1, 0, 0)
    scene.camera = cam

    import tempfile
    out_png = os.path.join(tempfile.mkdtemp(), "smoke_clouds.png")
    scene.render.filepath = out_png
    bpy.ops.render.render(write_still=True)
    assert Path(out_png).exists(), f"render did not produce output at {out_png}"

    print("smoke_clouds OK")


main()
