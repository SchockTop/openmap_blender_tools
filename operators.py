"""Thin bpy.types.Operator wrappers for the pure-Python functions.

These register only when the package is loaded as a Blender extension; running
outside Blender (pytest with mocked bpy, or the `blender-tools` CLI) does not
touch this module.
"""
from __future__ import annotations

import bpy
from bpy.props import (
    StringProperty,
    FloatVectorProperty,
    EnumProperty,
    IntProperty,
    BoolProperty,
)

import subprocess
from pathlib import Path

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


class BLENDERTOOLS_OT_full_pipeline(bpy.types.Operator):
    """Run the full OpenMap_Workflow pipeline (download + GDAL + scene assembly)."""

    bl_idname = "blender_tools.full_pipeline"
    bl_label = "Build cinematic scene from region"
    bl_options = {"REGISTER"}

    region: EnumProperty(
        name="Region",
        items=[
            ("muc-marienplatz-50m", "Marienplatz 50 m (smoke)", "1 km tile"),
            ("muc-sued-4x2",        "Munich south 4x2 km",     "8 DGM1 tiles"),
            ("muc-sued-10x4",       "Munich south 10x4 km",    "40 DGM1 (cinematic baseline)"),
        ],
        default="muc-sued-4x2",
    )
    engine: EnumProperty(
        name="Render engine",
        items=[
            ("BLENDER_EEVEE_NEXT", "Eevee Next (fast)", ""),
            ("CYCLES",             "Cycles (path-traced)", ""),
        ],
        default="BLENDER_EEVEE_NEXT",
    )
    render_preview: BoolProperty(
        name="Render preview frame",
        default=False,
    )
    workflow_root: StringProperty(
        name="OpenMap_Workflow root",
        subtype="DIR_PATH",
        default=r"G:\Privat\Projekte\Work\OpenMap_Workflow",
    )

    def execute(self, context):
        root = Path(self.workflow_root)
        script = root / "workflows" / "full_pipeline.py"
        if not script.is_file():
            self.report({"ERROR"}, f"full_pipeline.py not found at {script}")
            return {"CANCELLED"}
        cmd = [
            "python", str(script),
            "--region", self.region,
            "--engine", self.engine,
        ]
        if self.render_preview:
            cmd.append("--render-preview")
        self.report({"INFO"}, f"Running: {' '.join(cmd)} (see system console)")
        subprocess.Popen(cmd, cwd=str(root))
        return {"FINISHED"}


class BLENDERTOOLS_PT_panel(bpy.types.Panel):
    bl_label = "OpenMap Workflow"
    bl_idname = "BLENDERTOOLS_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OpenMap"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="One-click pipeline:")
        col.operator(BLENDERTOOLS_OT_full_pipeline.bl_idname, icon="WORLD")
        col.separator()
        col.label(text="Individual steps:")
        col.operator(BLENDERTOOLS_OT_setup_sky.bl_idname)
        col.operator(BLENDERTOOLS_OT_add_domain_cube.bl_idname)
        col.operator(BLENDERTOOLS_OT_cull_hidden.bl_idname)


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
    BLENDERTOOLS_OT_full_pipeline,
    BLENDERTOOLS_MT_main_menu,
    BLENDERTOOLS_PT_panel,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_add.append(_draw_in_add_menu)


def unregister() -> None:
    bpy.types.VIEW3D_MT_add.remove(_draw_in_add_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
