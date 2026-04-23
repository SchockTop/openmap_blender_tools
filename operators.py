"""Thin bpy.types.Operator wrappers for the pure-Python functions.

These register only when the package is loaded as a Blender extension; running
outside Blender (pytest with mocked bpy, or the `blender-tools` CLI) does not
touch this module.
"""
from __future__ import annotations

import bpy
from bpy.props import StringProperty, FloatVectorProperty, EnumProperty, IntProperty

from . import world_setup, hidden_geo_cull


_SKY_PRESETS = [
    ("client-default", "Client Default", "Bavarian rocket client baseline"),
    ("airbus-clean", "Airbus Clean", "Corporate clean, minimal haze"),
    ("spacex-warm", "SpaceX Warm", "Warmer, long-lens compression"),
]


class BLENDERTOOLS_OT_setup_sky(bpy.types.Operator):
    """Configure world sky + atmosphere from a named preset."""

    bl_idname = "blender_tools.setup_sky"
    bl_label = "Setup Multiple-Scattering Sky"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        name="Preset",
        items=_SKY_PRESETS,
        default="client-default",
    )

    def execute(self, context):
        world_setup.setup_multiple_scattering_sky(preset=self.preset)
        self.report({"INFO"}, f"Sky configured: {self.preset}")
        return {"FINISHED"}


class BLENDERTOOLS_OT_add_domain_cube(bpy.types.Operator):
    """Add a volumetric haze domain cube enclosing a bbox."""

    bl_idname = "blender_tools.add_domain_cube"
    bl_label = "Add Aerial Haze Domain Cube"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        name="Preset",
        items=_SKY_PRESETS,
        default="client-default",
    )
    bbox: FloatVectorProperty(
        name="BBox (m)",
        description="XYZ extents in metres",
        default=(1000.0, 1000.0, 500.0),
        min=1.0,
    )

    def execute(self, context):
        world_setup.add_domain_cube_volume(tuple(self.bbox), preset=self.preset)
        self.report({"INFO"}, f"Domain cube added ({self.preset})")
        return {"FINISHED"}


class BLENDERTOOLS_OT_cull_hidden(bpy.types.Operator):
    """Move objects matching a name regex into a _Hidden collection."""

    bl_idname = "blender_tools.cull_hidden"
    bl_label = "Cull Hidden Geometry (by name)"
    bl_options = {"REGISTER", "UNDO"}

    pattern: StringProperty(
        name="Regex Pattern",
        description="Python regex; objects whose name matches go to _Hidden",
        default=r"_hidden_.*",
    )

    def execute(self, context):
        n = hidden_geo_cull.cull_by_name_pattern(patterns=[self.pattern])
        self.report({"INFO"}, f"Culled {n} object(s)")
        return {"FINISHED"}


class BLENDERTOOLS_MT_main_menu(bpy.types.Menu):
    bl_idname = "BLENDERTOOLS_MT_main_menu"
    bl_label = "IR-Unity Blender Tools"

    def draw(self, context):
        layout = self.layout
        layout.operator(BLENDERTOOLS_OT_setup_sky.bl_idname)
        layout.operator(BLENDERTOOLS_OT_add_domain_cube.bl_idname)
        layout.operator(BLENDERTOOLS_OT_cull_hidden.bl_idname)


def _draw_in_add_menu(self, context):
    self.layout.separator()
    self.layout.menu(BLENDERTOOLS_MT_main_menu.bl_idname)


CLASSES = (
    BLENDERTOOLS_OT_setup_sky,
    BLENDERTOOLS_OT_add_domain_cube,
    BLENDERTOOLS_OT_cull_hidden,
    BLENDERTOOLS_MT_main_menu,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_add.append(_draw_in_add_menu)


def unregister() -> None:
    bpy.types.VIEW3D_MT_add.remove(_draw_in_add_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
