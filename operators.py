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
    FloatProperty,
)

import os
import subprocess
from pathlib import Path

_DEFAULT_WORKFLOW_ROOT = os.environ.get(
    "OPENMAP_WORKFLOW_ROOT",
    str(Path(__file__).resolve().parent.parent),  # assumes addon is a submodule of workflow
)

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
    camera_preset: EnumProperty(
        name="Camera preset",
        items=[
            ("fpv-walk",                "FPV walking (1.7 m, 1.4 m/s, 24 mm)", ""),
            ("fpv-bike",                "FPV bike (1.7 m, 6 m/s, 18 mm)",       ""),
            ("low-drone",               "Low drone (80 m, 10 m/s, 24 mm)",      ""),
            ("mid-drone",               "Mid drone (500 m, 30 m/s, 50 mm)",     ""),
            ("cinematic-establishing",  "Cinematic (2000 m, 70 m/s, 85 mm)",    ""),
            ("aircraft-approach",       "Aircraft (4500 m, 150 m/s, 135 mm)",   ""),
        ],
        default="cinematic-establishing",
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
        default=_DEFAULT_WORKFLOW_ROOT,
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
            "--camera-preset", self.camera_preset,
        ]
        if self.render_preview:
            cmd.append("--render-preview")
        self.report({"INFO"}, f"Running: {' '.join(cmd)} (see system console)")
        subprocess.Popen(cmd, cwd=str(root))
        return {"FINISHED"}


class BLENDERTOOLS_OT_import_csv_path(bpy.types.Operator):
    """Import a CSV file as a Bezier path."""

    bl_idname = "blender_tools.import_csv_path"
    bl_label = "Import CSV as path"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})
    name: StringProperty(name="Curve name", default="ImportedPath")
    use_scene_anchor: BoolProperty(
        name="Use scene anchor (utm32n_anchor)",
        description="Subtract the scene's stored utm32n_anchor for float32 precision",
        default=True,
    )

    def execute(self, context):
        from . import csv_curve_import
        anchor = (0.0, 0.0, 0.0)
        if self.use_scene_anchor and "utm32n_anchor" in context.scene:
            anchor = tuple(context.scene["utm32n_anchor"])
        try:
            curve = csv_curve_import.csv_to_blender_curve(
                self.filepath, anchor_utm32n=anchor, name=self.name)
        except Exception as e:
            self.report({"ERROR"}, f"CSV import failed: {e}")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        curve.select_set(True)
        context.view_layer.objects.active = curve
        self.report({"INFO"}, f"Imported {curve.name}; select an object then Attach to Path")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_attach_to_path(bpy.types.Operator):
    """Attach the active object to the selected curve (or single curve in scene)."""

    bl_idname = "blender_tools.attach_to_path"
    bl_label = "Attach selected object to path"
    bl_options = {"REGISTER", "UNDO"}

    speed_mps: FloatProperty(name="Speed (m/s)", default=10.0, min=0.0)
    fps: FloatProperty(name="FPS", default=25.0, min=1.0)
    heading_axis: EnumProperty(
        name="Forward axis",
        items=[
            ("TRACK_NEGATIVE_Y", "-Y (Blender default)", ""),
            ("FORWARD_X", "+X", ""),
            ("FORWARD_Y", "+Y", ""),
            ("FORWARD_Z", "+Z", ""),
        ],
        default="TRACK_NEGATIVE_Y",
    )

    def execute(self, context):
        from . import csv_curve_import
        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object - select something to attach")
            return {"CANCELLED"}
        curves = [o for o in context.selected_objects if o.type == "CURVE" and o is not obj]
        if not curves:
            curves = [o for o in bpy.data.objects if o.type == "CURVE"]
        if not curves:
            self.report({"ERROR"}, "No curve found - import a CSV path first")
            return {"CANCELLED"}
        curve = curves[0]
        if obj.type == "CURVE":
            self.report({"ERROR"}, "Active object is a curve; select the OBJECT to attach (mesh/empty)")
            return {"CANCELLED"}
        result = csv_curve_import.attach_object_to_curve(
            obj, curve, fps=self.fps, speed_mps=self.speed_mps,
            heading_axis=self.heading_axis,
        )
        self.report({"INFO"}, f"Attached {obj.name} to {curve.name}: "
                              f"{result['arc_length_m']:.0f} m / "
                              f"{result['duration_frames']} frames")
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
        col.separator()
        col.label(text="Animation:")
        col.operator(BLENDERTOOLS_OT_import_csv_path.bl_idname, icon="CURVE_DATA")
        col.operator(BLENDERTOOLS_OT_attach_to_path.bl_idname, icon="CON_FOLLOWPATH")


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
    BLENDERTOOLS_OT_import_csv_path,
    BLENDERTOOLS_OT_attach_to_path,
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
