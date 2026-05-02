"""altitude_handler.py — render_pre handler for camera-altitude-driven DOP weight.

Drivers reading object transforms into shader inputs are unreliable during
render (Blender T78893, #113930). Instead, we register a render_pre handler
that writes the computed weight into the DropDrapeMix node's Fac input
before each render.

Curve:
  z <= 100 m   -> weight 0.6 (procedural-leaning)
  z >= 1000 m  -> weight 0.15 (DOP-leaning)
  100 < z < 1000 -> linear interp between
"""
from __future__ import annotations

GROUND_MAT_NAME = "GroundShader_Layered"
MIX_NODE_NAME = "DropDrapeMix"
WEIGHT_LOW = 0.6
WEIGHT_HIGH = 0.15
ALT_LOW = 100.0
ALT_HIGH = 1000.0


def compute_weight(cam_z: float) -> float:
    if cam_z <= ALT_LOW:
        return WEIGHT_LOW
    if cam_z >= ALT_HIGH:
        return WEIGHT_HIGH
    t = (cam_z - ALT_LOW) / (ALT_HIGH - ALT_LOW)
    return WEIGHT_LOW + t * (WEIGHT_HIGH - WEIGHT_LOW)


def update_drape_weight(scene, _bpy=None):
    """Read scene.camera.location.z, write weight into the ground shader mix node."""
    if _bpy is None:
        import bpy as _bpy  # noqa: F811
    cam = getattr(scene, "camera", None)
    if cam is None:
        return
    cam_z = cam.location.z
    weight = compute_weight(cam_z)
    mat = _bpy.data.materials.get(GROUND_MAT_NAME)
    if mat is None or mat.node_tree is None:
        return
    nodes = mat.node_tree.nodes
    mix = nodes.get(MIX_NODE_NAME)
    if mix is None:
        return
    mix.inputs["Fac"].default_value = weight


def register():
    """Register the handler with Blender's render_pre."""
    import bpy
    if update_drape_weight not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(update_drape_weight)


def unregister():
    import bpy
    if update_drape_weight in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(update_drape_weight)
