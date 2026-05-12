"""Headless smoke test: build a tiny cutout.glb + meta.json, run the operator,
assert objects imported and translated. Needs Blender.

Run: blender --background --python tests/smoke_dommesh.py
"""
import json
import os
import sys
import tempfile

import bpy

# --- build a 1-triangle GLB the same way backend/dommesh.write_glb does, but
#     standalone (this file can't import OpenMap_Unifier). Minimal valid glTF: ---
import struct


def _pad4(b, fill=b"\x00"):
    return b + fill * ((4 - len(b) % 4) % 4)


def _tiny_glb(path):
    # one triangle, Y-up, no texture (keep it minimal — colorspace path is
    # exercised by the unit test's mock; here we only need geometry to land).
    verts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 0.0, -10.0)]
    idx = struct.pack("<III", 0, 1, 2)   # 12 bytes, already 4-aligned
    pos = b"".join(struct.pack("<fff", *v) for v in verts)  # 36 bytes
    bin_blob = _pad4(idx + pos)           # 48 bytes total
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0, "mode": 4}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5125, "count": 3, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3",
             "min": [0.0, 0.0, -10.0], "max": [10.0, 0.0, 0.0]},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 12, "target": 34963},
            {"buffer": 0, "byteOffset": 12, "byteLength": 36, "target": 34962},
        ],
        "buffers": [{"byteLength": len(bin_blob)}],
    }
    jb = _pad4(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    total = 12 + 8 + len(jb) + 8 + len(bin_blob)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<4sII", b"glTF", 2, total))
        fh.write(struct.pack("<I4s", len(jb), b"JSON")); fh.write(jb)
        fh.write(struct.pack("<I4s", len(bin_blob), b"BIN\x00")); fh.write(bin_blob)


def main():
    # Make the addon importable as `blender_tools`.
    # openmap_blender_tools/ IS the blender_tools package (pyproject.toml maps it).
    # Inside Blender (no pip install), we register it manually via sys.modules.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent = os.path.dirname(repo)  # OpenMap_Workflow/

    try:
        import blender_tools  # noqa: F401
    except ModuleNotFoundError:
        # openmap_blender_tools/ is the package root; expose it as blender_tools.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "blender_tools", os.path.join(repo, "__init__.py"),
            submodule_search_locations=[repo],
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["blender_tools"] = mod
        spec.loader.exec_module(mod)

    from blender_tools import dommesh_import

    d = tempfile.mkdtemp()
    glb = os.path.join(d, "cutout.glb")
    _tiny_glb(glb)
    json.dump({"losid": "T", "anchor_epsg25832": [690000.0, 5506000.0]},
              open(os.path.join(d, "meta.json"), "w"))

    # Empty scene.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    res = dommesh_import.import_dommesh_glb(glb, meta_path=os.path.join(d, "meta.json"),
                                            scene_anchor=None)
    assert res["objects"], "no objects imported"
    assert res["empty"].name == "DOM-Mesh"
    anchor = bpy.context.scene.get("utm32n_anchor")
    assert anchor is not None, "utm32n_anchor not set"
    # anchor is stored as [x, y, 0.0]; check the easting/northing values.
    assert list(anchor)[:2] == [690000.0, 5506000.0], f"unexpected anchor: {list(anchor)}"
    print("smoke_dommesh OK:", len(res["objects"]), "object(s)")


main()
