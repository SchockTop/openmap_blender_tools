"""Blender operators and N-panel UI for OpenMap blender_tools.

Registers operators for every major feature: geo-import, scene setup,
camera, quick-actions, and tools. Organized into collapsible sub-panels
under the "OpenMap" N-panel tab.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)

_DEFAULT_WORKFLOW_ROOT = os.environ.get(
    "OPENMAP_WORKFLOW_ROOT",
    str(Path(__file__).resolve().parent.parent),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_terrain(context):
    scene = context.scene
    name = scene.get("terrain_object_name")
    if name and name in bpy.data.objects:
        return bpy.data.objects[name]
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.name.startswith("Terrain"):
            return obj
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            for mod in obj.modifiers:
                if mod.type == "DISPLACE":
                    return obj
    return context.active_object


def _find_buildings(context):
    for coll in bpy.data.collections:
        if coll.name in ("Buildings", "CityJSON"):
            return [o for o in coll.objects if o.type == "MESH"]
    return []


def _get_scene_anchor(context):
    anchor = context.scene.get("utm32n_anchor")
    if anchor:
        return tuple(anchor)
    return (0.0, 0.0, 0.0)


def _get_scene_bbox(context):
    bbox = context.scene.get("bbox_utm32n")
    if bbox:
        return tuple(bbox)
    return None


def _build_feature_context(context, terrain=None, buildings=None):
    terrain = terrain or _find_terrain(context)
    buildings = buildings or _find_buildings(context)
    anchor = _get_scene_anchor(context)
    bbox = _get_scene_bbox(context)
    ctx = {
        "bpy": bpy,
        "scene": context.scene,
        "anchor_utm32n": anchor,
    }
    if terrain:
        ctx["terrain_obj"] = terrain
    if buildings:
        ctx["building_objs"] = buildings
    if bbox:
        ctx["bbox_utm32n"] = bbox
    ortho_dir = context.scene.get("ortho_dir")
    if ortho_dir:
        ctx["ortho_dir"] = ortho_dir
    return ctx


# ---------------------------------------------------------------------------
# Import Operators
# ---------------------------------------------------------------------------

class BLENDERTOOLS_OT_import_heightmap(bpy.types.Operator):
    """Import DGM GeoTIFF(s) as a terrain mesh with displacement."""

    bl_idname = "blender_tools.import_heightmap"
    bl_label = "Import Heightmap"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    directory: StringProperty(subtype="DIR_PATH")
    filter_glob: StringProperty(default="*.tif;*.tiff", options={"HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    subdivisions: IntProperty(name="Subdivisions", default=8, min=1, max=12)
    strength: FloatProperty(name="Displacement strength", default=1.0, min=0.01)

    def execute(self, context):
        from . import geo_import, terrain_setup

        directory = Path(self.directory) if self.directory else Path(self.filepath).parent
        tifs = []
        if self.files:
            for f in self.files:
                p = directory / f.name
                if p.suffix.lower() in (".tif", ".tiff") and p.is_file():
                    tifs.append(p)
        if not tifs and self.filepath:
            fp = Path(self.filepath)
            if fp.is_file():
                tifs = [fp]
        if not tifs:
            tifs = sorted(directory.glob("*.tif")) + sorted(directory.glob("*.tiff"))
        if not tifs:
            self.report({"ERROR"}, "No .tif files selected")
            return {"CANCELLED"}

        # Mosaic into a single heightmap, then read metadata via gdalinfo.
        proc_dir = directory / "_openmap_processed"
        proc_dir.mkdir(parents=True, exist_ok=True)
        heightmap_path = proc_dir / "heightmap.tif"

        try:
            geo_import.dgm_tif_to_heightmap(tifs, heightmap_path)
        except Exception as e:
            self.report({"ERROR"}, f"GDAL mosaic failed: {e}")
            return {"CANCELLED"}

        try:
            meta = geo_import.geotiff_metadata(heightmap_path)
        except Exception as e:
            self.report({"ERROR"}, f"Cannot read heightmap metadata: {e}")
            return {"CANCELLED"}

        size = (meta["size_meters_x"], meta["size_meters_y"])
        anchor = (meta["origin_x"], meta["origin_y"] - meta["size_meters_y"], 0.0)
        context.scene["utm32n_anchor"] = list(anchor)
        context.scene["bbox_utm32n"] = [
            anchor[0], anchor[1],
            anchor[0] + size[0], anchor[1] + size[1],
        ]

        terrain = terrain_setup.build_terrain_from_heightmap(
            str(heightmap_path),
            size_meters=size,
            subdivisions=self.subdivisions,
            strength=self.strength,
            anchor_utm32n=anchor,
        )
        context.scene["terrain_object_name"] = terrain.name
        self.report({"INFO"}, f"Terrain: {terrain.name} ({size[0]:.0f}×{size[1]:.0f} m)")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_import_dgm5_zip(bpy.types.Operator):
    """Convert DGM5 XYZ-ASCII .zip files to GeoTIFF and optionally build terrain."""

    bl_idname = "blender_tools.import_dgm5_zip"
    bl_label = "Import DGM5 ZIP"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    build_terrain: BoolProperty(name="Build terrain mesh", default=True)
    subdivisions: IntProperty(name="Subdivisions", default=9, min=1, max=15)

    def execute(self, context):
        from . import geo_import

        directory = Path(self.directory)
        zips = []
        if self.files:
            for f in self.files:
                p = directory / f.name
                if p.suffix.lower() == ".zip" and p.is_file():
                    zips.append(p)
        if not zips:
            zips = sorted(directory.glob("*.zip"))
        if not zips:
            self.report({"ERROR"}, "No .zip files found")
            return {"CANCELLED"}

        out_dir = directory / "converted_tifs"
        try:
            tifs = geo_import.dgm5_xyz_to_geotiffs(zips, out_dir)
        except Exception as e:
            self.report({"ERROR"}, f"DGM5 conversion failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Converted {len(tifs)} GeoTIFFs to {out_dir}")

        if self.build_terrain and tifs:
            bpy.ops.blender_tools.import_heightmap(
                "EXEC_DEFAULT",
                directory=str(out_dir),
                subdivisions=self.subdivisions,
            )

        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_import_ortho(bpy.types.Operator):
    """Import DOP orthophoto tiles and drape onto terrain as UDIM material."""

    bl_idname = "blender_tools.import_ortho"
    bl_label = "Import Orthophoto"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    filter_glob: StringProperty(default="*.tif;*.tiff", options={"HIDDEN"})
    tile_resolution: IntProperty(name="Tile resolution (px)", default=2048, min=256, max=8192)

    def execute(self, context):
        import math
        from . import geo_import, terrain_setup

        directory = Path(self.directory)
        tifs = sorted(directory.glob("*.tif")) + sorted(directory.glob("*.tiff"))
        if not tifs:
            self.report({"ERROR"}, f"No .tif files in {directory}")
            return {"CANCELLED"}

        terrain = _find_terrain(context)
        if not terrain:
            self.report({"ERROR"}, "No terrain object found — import a heightmap first")
            return {"CANCELLED"}

        bbox = _get_scene_bbox(context)
        if not bbox:
            dims = terrain.dimensions
            anchor = _get_scene_anchor(context)
            bbox = (anchor[0], anchor[1],
                    anchor[0] + dims.x, anchor[1] + dims.y)
            context.scene["bbox_utm32n"] = list(bbox)

        udim_dir = directory.parent / "ortho_udim"
        size_x = bbox[2] - bbox[0]
        size_y = bbox[3] - bbox[1]
        u_tiles = max(1, min(10, int(math.ceil(size_x / 1000))))
        v_tiles = max(1, int(math.ceil(size_y / 1000)))

        geo_import.dop_to_udim_tiles(
            tifs, bbox_utm32n=bbox, output_dir=udim_dir,
            tile_grid=(u_tiles, v_tiles),
            resolution_per_tile=self.tile_resolution,
        )

        terrain_setup.apply_ortho_drape(terrain, str(udim_dir))
        context.scene["ortho_dir"] = str(udim_dir)
        self.report({"INFO"}, f"Ortho drape applied ({u_tiles}×{v_tiles} UDIM tiles)")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_import_buildings(bpy.types.Operator):
    """Import CityGML (.gml) or CityJSON (.cityjson) as building meshes."""

    bl_idname = "blender_tools.import_buildings"
    bl_label = "Import Buildings"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.gml;*.xml;*.cityjson;*.json", options={"HIDDEN"})
    collection_name: StringProperty(name="Collection", default="Buildings")

    def execute(self, context):
        from . import citygml_import

        fp = Path(self.filepath)
        if not fp.is_file():
            self.report({"ERROR"}, f"File not found: {fp}")
            return {"CANCELLED"}

        anchor = _get_scene_anchor(context)

        if fp.suffix.lower() in (".gml", ".xml"):
            cityjson_path = fp.with_suffix(".cityjson")
            citygml_import.gml_to_cityjson_pure([fp], cityjson_path)
        else:
            cityjson_path = fp

        buildings = citygml_import.cityjson_to_blender(
            cityjson_path,
            anchor_utm32n=anchor,
            collection_name=self.collection_name,
        )
        context.scene["building_collection_name"] = self.collection_name
        self.report({"INFO"}, f"Imported {len(buildings)} building(s) into '{self.collection_name}'")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_import_vdb_cloud(bpy.types.Operator):
    """Import a VDB volume as a cloud object."""

    bl_idname = "blender_tools.import_vdb_cloud"
    bl_label = "Import VDB Cloud"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.vdb", options={"HIDDEN"})
    altitude: FloatProperty(name="Altitude (m)", default=2000.0, min=0.0)
    scale: FloatProperty(name="Scale", default=500.0, min=1.0)

    def execute(self, context):
        from . import world_setup

        fp = Path(self.filepath)
        if not fp.is_file():
            self.report({"ERROR"}, f"File not found: {fp}")
            return {"CANCELLED"}

        obj = world_setup.load_vdb_cloud(
            str(fp),
            position=(0, 0, self.altitude),
            scale=self.scale,
        )
        self.report({"INFO"}, f"VDB cloud imported: {obj.name}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_import_csv_path(bpy.types.Operator):
    """Import a CSV file as a Bezier path."""

    bl_idname = "blender_tools.import_csv_path"
    bl_label = "Import Flight Path"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})
    name: StringProperty(name="Curve name", default="ImportedPath")

    def execute(self, context):
        from . import csv_curve_import

        anchor = _get_scene_anchor(context)
        try:
            curve = csv_curve_import.csv_to_blender_curve(
                self.filepath, anchor_utm32n=anchor, name=self.name)
        except Exception as e:
            self.report({"ERROR"}, f"CSV import failed: {e}")
            return {"CANCELLED"}
        bpy.ops.object.select_all(action="DESELECT")
        curve.select_set(True)
        context.view_layer.objects.active = curve
        self.report({"INFO"}, f"Imported path: {curve.name}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


# ---------------------------------------------------------------------------
# Scene Setup Operators
# ---------------------------------------------------------------------------

_SKY_PRESETS = [
    ("noon",          "Noon",         "Direct overhead, cool white"),
    ("golden-hour",   "Golden Hour",  "Warm long shadows, low sun"),
    ("blue-hour",     "Blue Hour",    "Post-sunset twilight"),
    ("dawn",          "Dawn",         "Soft pink east-facing"),
    ("overcast",      "Overcast",     "Flat diffuse, no shadows"),
    ("afternoon",     "Afternoon",    "Default cinematic, moderate warmth"),
]

_QUALITY_PRESETS = [
    ("draft",   "Draft (480p)",   "Fast preview, skips groundcover"),
    ("preview", "Preview (540p)", "Balanced quality"),
    ("final",   "Final (1080p)",  "Full resolution, max samples"),
]


class BLENDERTOOLS_OT_apply_sky_preset(bpy.types.Operator):
    """Apply a time-of-day sky lighting preset."""

    bl_idname = "blender_tools.apply_sky_preset"
    bl_label = "Apply Sky Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Sky", items=_SKY_PRESETS, default="afternoon")

    def execute(self, context):
        from . import sky_presets
        sky_presets.apply_sky_preset(context.scene, self.preset)
        self.report({"INFO"}, f"Sky: {self.preset}")
        return {"FINISHED"}


class BLENDERTOOLS_OT_apply_quality(bpy.types.Operator):
    """Apply a render quality preset (draft / preview / final)."""

    bl_idname = "blender_tools.apply_quality"
    bl_label = "Apply Quality"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Quality", items=_QUALITY_PRESETS, default="preview")

    def execute(self, context):
        from . import quality_presets
        quality_presets.apply_quality(context.scene, self.preset)
        self.report({"INFO"}, f"Quality: {self.preset}")
        return {"FINISHED"}


class BLENDERTOOLS_OT_apply_ground_shader(bpy.types.Operator):
    """Apply procedural ground material (grass, rock, forest, field) to terrain."""

    bl_idname = "blender_tools.apply_ground_shader"
    bl_label = "Apply Ground Shader"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .features import ground_shader

        terrain = _find_terrain(context)
        if not terrain:
            self.report({"ERROR"}, "No terrain found")
            return {"CANCELLED"}
        ctx = _build_feature_context(context, terrain=terrain)
        ground_shader.apply(ctx)
        self.report({"INFO"}, "Ground shader applied to terrain")
        return {"FINISHED"}


class BLENDERTOOLS_OT_apply_building_textures(bpy.types.Operator):
    """Apply roof DOP projection + wall PBR materials to buildings."""

    bl_idname = "blender_tools.apply_building_textures"
    bl_label = "Apply Building Textures"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .features import buildings_textured

        buildings = _find_buildings(context)
        if not buildings:
            self.report({"ERROR"}, "No building objects found")
            return {"CANCELLED"}
        ctx = _build_feature_context(context, buildings=buildings)
        result = buildings_textured.apply(ctx)
        n = result.get("textured_count", len(buildings))
        self.report({"INFO"}, f"Textured {n} building(s)")
        return {"FINISHED"}


class BLENDERTOOLS_OT_scatter_trees(bpy.types.Operator):
    """Scatter tree instances on terrain via Geometry Nodes."""

    bl_idname = "blender_tools.scatter_trees"
    bl_label = "Scatter Trees"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .features import trees

        terrain = _find_terrain(context)
        if not terrain:
            self.report({"ERROR"}, "No terrain found")
            return {"CANCELLED"}
        ctx = _build_feature_context(context, terrain=terrain)
        result = trees.apply(ctx)
        self.report({"INFO"}, f"Trees scattered ({result.get('template_count', '?')} templates)")
        return {"FINISHED"}


class BLENDERTOOLS_OT_scatter_groundcover(bpy.types.Operator):
    """Scatter dense grass and bushes near camera path (FPV-altitude band)."""

    bl_idname = "blender_tools.scatter_groundcover"
    bl_label = "Scatter Groundcover"
    bl_options = {"REGISTER", "UNDO"}

    target_instances: IntProperty(
        name="Instance count", default=50000, min=1000, max=500000)

    def execute(self, context):
        from .features import groundcover

        terrain = _find_terrain(context)
        if not terrain:
            self.report({"ERROR"}, "No terrain found")
            return {"CANCELLED"}
        ctx = _build_feature_context(context, terrain=terrain)
        ctx["args"] = {"groundcover_target_instances": self.target_instances}
        result = groundcover.apply(ctx)
        self.report({"INFO"}, f"Groundcover: {result.get('density', '?')} instances")
        return {"FINISHED"}


class BLENDERTOOLS_OT_add_domain_cube(bpy.types.Operator):
    """Add volumetric aerial haze domain cube."""

    bl_idname = "blender_tools.add_domain_cube"
    bl_label = "Add Aerial Haze"
    bl_options = {"REGISTER", "UNDO"}

    bbox_x: FloatProperty(name="X extent (m)", default=10000.0, min=100.0)
    bbox_y: FloatProperty(name="Y extent (m)", default=10000.0, min=100.0)
    bbox_z: FloatProperty(name="Z extent (m)", default=5000.0, min=100.0)

    def execute(self, context):
        from . import world_setup
        world_setup.add_domain_cube_volume(
            (self.bbox_x, self.bbox_y, self.bbox_z))
        self.report({"INFO"}, "Haze domain cube added")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Camera Operators
# ---------------------------------------------------------------------------

_CAMERA_PRESETS = [
    ("fpv-walk",               "FPV Walk (1.7m, 24mm)",      "Handheld walking"),
    ("fpv-bike",               "FPV Bike (1.7m, 18mm)",      "Bike-mount"),
    ("low-drone",              "Low Drone (80m, 24mm)",       "Building facades"),
    ("mid-drone",              "Mid Drone (500m, 50mm)",      "Corporate flight"),
    ("cinematic-establishing", "Cinematic (800m, 50mm)",      "Feature film default"),
    ("aircraft-approach",      "Aircraft (4500m, 135mm)",     "High-altitude reveal"),
]


class BLENDERTOOLS_OT_apply_camera_preset(bpy.types.Operator):
    """Apply a camera altitude/lens/speed preset to the active camera."""

    bl_idname = "blender_tools.apply_camera_preset"
    bl_label = "Apply Camera Preset"
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(name="Camera", items=_CAMERA_PRESETS,
                         default="cinematic-establishing")

    def execute(self, context):
        from . import camera_presets

        cam = context.scene.camera
        if cam is None:
            self.report({"ERROR"}, "No active camera in scene")
            return {"CANCELLED"}
        camera_presets.apply_camera_preset(cam, self.preset, scene=context.scene)
        self.report({"INFO"}, f"Camera preset: {self.preset}")
        return {"FINISHED"}


class BLENDERTOOLS_OT_setup_camera_rig(bpy.types.Operator):
    """Create a camera and attach it to a curve path with banking."""

    bl_idname = "blender_tools.setup_camera_rig"
    bl_label = "Setup Camera Rig"
    bl_options = {"REGISTER", "UNDO"}

    banking_max_deg: FloatProperty(name="Max banking (°)", default=8.0, min=0.0, max=45.0)
    speed_mps: FloatProperty(name="Speed (m/s)", default=50.0, min=0.1)

    def execute(self, context):
        from . import waypoints_to_camera

        curves = [o for o in bpy.data.objects if o.type == "CURVE"]
        if not curves:
            self.report({"ERROR"}, "No curve in scene — import a flight path first")
            return {"CANCELLED"}
        curve = curves[0]
        cam = waypoints_to_camera.attach_camera_rig(
            curve,
            banking_max_deg=self.banking_max_deg,
        )
        context.scene.camera = cam
        self.report({"INFO"}, f"Camera rig: {cam.name} on {curve.name}")
        return {"FINISHED"}


class BLENDERTOOLS_OT_attach_to_path(bpy.types.Operator):
    """Attach the active object to the selected curve."""

    bl_idname = "blender_tools.attach_to_path"
    bl_label = "Attach to Path"
    bl_options = {"REGISTER", "UNDO"}

    speed_mps: FloatProperty(name="Speed (m/s)", default=10.0, min=0.0)
    fps: FloatProperty(name="FPS", default=25.0, min=1.0)

    def execute(self, context):
        from . import csv_curve_import

        obj = context.active_object
        if obj is None:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}
        curves = [o for o in context.selected_objects if o.type == "CURVE" and o is not obj]
        if not curves:
            curves = [o for o in bpy.data.objects if o.type == "CURVE"]
        if not curves:
            self.report({"ERROR"}, "No curve found")
            return {"CANCELLED"}
        result = csv_curve_import.attach_object_to_curve(
            obj, curves[0], fps=self.fps, speed_mps=self.speed_mps)
        self.report({"INFO"}, f"Attached {obj.name}: {result['arc_length_m']:.0f}m, "
                              f"{result['duration_frames']} frames")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Quick Actions
# ---------------------------------------------------------------------------

class BLENDERTOOLS_OT_quick_scene_from_folder(bpy.types.Operator):
    """Auto-detect DGM/DOP/GML in a folder and build a complete scene."""

    bl_idname = "blender_tools.quick_scene_from_folder"
    bl_label = "Quick Scene from Folder"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    sky_preset: EnumProperty(name="Sky", items=_SKY_PRESETS, default="afternoon")
    quality: EnumProperty(name="Quality", items=_QUALITY_PRESETS, default="preview")
    import_buildings: BoolProperty(name="Import buildings", default=True)
    apply_ground: BoolProperty(name="Apply ground shader", default=True)
    apply_trees: BoolProperty(name="Scatter trees", default=True)

    def execute(self, context):
        directory = Path(self.directory)
        if not directory.is_dir():
            self.report({"ERROR"}, f"Not a directory: {directory}")
            return {"CANCELLED"}

        tifs = sorted(directory.rglob("*.tif")) + sorted(directory.rglob("*.tiff"))
        zips = sorted(directory.rglob("*.zip"))
        gmls = sorted(directory.rglob("*.gml")) + sorted(directory.rglob("*.xml"))
        cityjsons = sorted(directory.rglob("*.cityjson"))

        dgm_tifs = [t for t in tifs if "dgm" in str(t).lower() or "dem" in str(t).lower()
                     or "height" in str(t).lower()]
        dop_tifs = [t for t in tifs if "dop" in str(t).lower() or "ortho" in str(t).lower()]

        if not dgm_tifs and not dop_tifs:
            small = [t for t in tifs if t.stat().st_size < 20_000_000]
            large = [t for t in tifs if t.stat().st_size >= 20_000_000]
            dgm_tifs = small if small else tifs
            dop_tifs = large

        dgm5_zips = [z for z in zips if "dgm" in str(z).lower() or z.parent.name.startswith("dgm")]

        steps_done = []

        # 1. Heightmap
        if dgm_tifs:
            bpy.ops.blender_tools.import_heightmap(
                "EXEC_DEFAULT", directory=str(dgm_tifs[0].parent))
            steps_done.append("heightmap")
        elif dgm5_zips:
            bpy.ops.blender_tools.import_dgm5_zip(
                "EXEC_DEFAULT", directory=str(dgm5_zips[0].parent))
            steps_done.append("heightmap (DGM5)")

        # 2. Ortho drape
        if dop_tifs and _find_terrain(context):
            bpy.ops.blender_tools.import_ortho(
                "EXEC_DEFAULT", directory=str(dop_tifs[0].parent))
            steps_done.append("ortho")

        # 3. Buildings
        building_file = None
        if self.import_buildings:
            if cityjsons:
                building_file = cityjsons[0]
            elif gmls:
                building_file = gmls[0]
        if building_file:
            bpy.ops.blender_tools.import_buildings(
                "EXEC_DEFAULT", filepath=str(building_file))
            steps_done.append("buildings")

        # 4. Sky
        bpy.ops.blender_tools.apply_sky_preset("EXEC_DEFAULT", preset=self.sky_preset)
        steps_done.append(f"sky:{self.sky_preset}")

        # 5. Quality
        bpy.ops.blender_tools.apply_quality("EXEC_DEFAULT", preset=self.quality)
        steps_done.append(f"quality:{self.quality}")

        # 6. Ground shader
        if self.apply_ground and _find_terrain(context):
            bpy.ops.blender_tools.apply_ground_shader("EXEC_DEFAULT")
            steps_done.append("ground shader")

        # 7. Trees
        if self.apply_trees and _find_terrain(context):
            bpy.ops.blender_tools.scatter_trees("EXEC_DEFAULT")
            steps_done.append("trees")

        # 8. Camera
        if not context.scene.camera:
            bpy.ops.object.camera_add()
            context.scene.camera = context.active_object
        bpy.ops.blender_tools.apply_camera_preset(
            "EXEC_DEFAULT", preset="cinematic-establishing")
        steps_done.append("camera")

        self.report({"INFO"}, f"Scene built: {', '.join(steps_done)}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_render_preview(bpy.types.Operator):
    """Set quality to preview and render the active camera."""

    bl_idname = "blender_tools.render_preview"
    bl_label = "Render Preview"
    bl_options = {"REGISTER"}

    def execute(self, context):
        bpy.ops.blender_tools.apply_quality("EXEC_DEFAULT", preset="preview")
        bpy.ops.render.render("INVOKE_DEFAULT")
        return {"FINISHED"}


class BLENDERTOOLS_OT_full_pipeline(bpy.types.Operator):
    """Run the full OpenMap_Workflow pipeline (download + GDAL + scene assembly)."""

    bl_idname = "blender_tools.full_pipeline"
    bl_label = "Full Pipeline (External)"
    bl_options = {"REGISTER"}

    region: EnumProperty(
        name="Region",
        items=[
            ("muc-marienplatz-50m", "Marienplatz 50 m", "1 tile, ~30 sec"),
            ("muc-sued-4x2",        "Munich south 4×2 km", "8 DGM1 tiles"),
            ("muc-sued-10x4",       "Munich south 10×4 km", "Cinematic baseline"),
        ],
        default="muc-sued-4x2",
    )
    engine: EnumProperty(
        name="Engine",
        items=[
            ("BLENDER_EEVEE_NEXT", "Eevee Next", ""),
            ("CYCLES",             "Cycles",     ""),
        ],
        default="BLENDER_EEVEE_NEXT",
    )
    workflow_root: StringProperty(
        name="Workflow root",
        subtype="DIR_PATH",
        default=_DEFAULT_WORKFLOW_ROOT,
    )

    def execute(self, context):
        root = Path(self.workflow_root)
        script = root / "workflows" / "full_pipeline.py"
        if not script.is_file():
            self.report({"ERROR"}, f"full_pipeline.py not found at {script}")
            return {"CANCELLED"}
        cmd = ["python", str(script), "--region", self.region, "--engine", self.engine]
        subprocess.Popen(cmd, cwd=str(root))
        self.report({"INFO"}, f"Pipeline started for {self.region}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Tool Operators
# ---------------------------------------------------------------------------

class BLENDERTOOLS_OT_cull_hidden(bpy.types.Operator):
    """Move objects matching a name regex into a _Hidden collection."""

    bl_idname = "blender_tools.cull_hidden"
    bl_label = "Cull Hidden Geometry"
    bl_options = {"REGISTER", "UNDO"}

    pattern: StringProperty(name="Regex", default=r"_hidden_.*")

    def execute(self, context):
        from . import hidden_geo_cull
        n = hidden_geo_cull.cull_by_name_pattern(patterns=[self.pattern])
        self.report({"INFO"}, f"Culled {n} object(s)")
        return {"FINISHED"}


class BLENDERTOOLS_OT_clean_cad_mesh(bpy.types.Operator):
    """Clean a mesh file through pymeshlab filters (dedup, manifold repair)."""

    bl_idname = "blender_tools.clean_cad_mesh"
    bl_label = "Clean CAD Mesh"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.obj;*.ply;*.stl;*.glb;*.gltf", options={"HIDDEN"})

    def execute(self, context):
        from . import cleanup_pymeshlab

        fp = Path(self.filepath)
        out = fp.with_stem(fp.stem + "_cleaned")
        try:
            cleanup_pymeshlab.clean_cad_mesh(fp, out)
        except Exception as e:
            self.report({"ERROR"}, f"Cleanup failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Cleaned mesh: {out}")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class BLENDERTOOLS_OT_compute_ndvi(bpy.types.Operator):
    """Compute NDVI from red + NIR band GeoTIFFs."""

    bl_idname = "blender_tools.compute_ndvi"
    bl_label = "Compute NDVI"
    bl_options = {"REGISTER"}

    red_path: StringProperty(name="Red band TIF", subtype="FILE_PATH")
    nir_path: StringProperty(name="NIR band TIF", subtype="FILE_PATH")

    def execute(self, context):
        from . import ndvi_scatter

        red = Path(self.red_path)
        nir = Path(self.nir_path)
        out = red.with_stem(red.stem + "_ndvi")
        try:
            ndvi_scatter.compute_ndvi(red, nir, out)
        except Exception as e:
            self.report({"ERROR"}, f"NDVI failed: {e}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"NDVI: {out}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

class BLENDERTOOLS_PT_import(bpy.types.Panel):
    bl_label = "Import Data"
    bl_idname = "BLENDERTOOLS_PT_import"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OpenMap"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("blender_tools.import_heightmap", icon="MESH_GRID")
        col.operator("blender_tools.import_dgm5_zip", icon="FILE_ARCHIVE")
        col.operator("blender_tools.import_ortho", icon="IMAGE_DATA")
        col.operator("blender_tools.import_buildings", icon="HOME")
        col.operator("blender_tools.import_csv_path", icon="CURVE_DATA")
        col.operator("blender_tools.import_vdb_cloud", icon="VOLUME_DATA")


class BLENDERTOOLS_PT_scene_setup(bpy.types.Panel):
    bl_label = "Scene Setup"
    bl_idname = "BLENDERTOOLS_PT_scene_setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OpenMap"

    def draw(self, context):
        col = self.layout.column(align=True)

        row = col.row(align=True)
        row.operator("blender_tools.apply_sky_preset", icon="LIGHT_SUN")

        row = col.row(align=True)
        row.operator("blender_tools.apply_quality", icon="RENDERLAYERS")

        col.separator()
        col.operator("blender_tools.apply_ground_shader", icon="TEXTURE")
        col.operator("blender_tools.apply_building_textures", icon="MATERIAL")
        col.operator("blender_tools.scatter_trees", icon="OUTLINER_OB_FORCE_FIELD")
        col.operator("blender_tools.scatter_groundcover", icon="HAIR")
        col.operator("blender_tools.add_domain_cube", icon="MOD_FLUID")


class BLENDERTOOLS_PT_camera(bpy.types.Panel):
    bl_label = "Camera"
    bl_idname = "BLENDERTOOLS_PT_camera"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OpenMap"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("blender_tools.apply_camera_preset", icon="CAMERA_DATA")
        col.operator("blender_tools.setup_camera_rig", icon="CON_CAMERASOLVER")
        col.operator("blender_tools.attach_to_path", icon="CON_FOLLOWPATH")


class BLENDERTOOLS_PT_quick_actions(bpy.types.Panel):
    bl_label = "Quick Actions"
    bl_idname = "BLENDERTOOLS_PT_quick_actions"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OpenMap"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("blender_tools.quick_scene_from_folder", icon="WORLD")
        col.operator("blender_tools.render_preview", icon="RENDER_STILL")
        col.separator()
        col.operator("blender_tools.full_pipeline", icon="PLAY")

        # Scene info
        scene = context.scene
        if scene.get("utm32n_anchor"):
            box = col.box()
            a = scene["utm32n_anchor"]
            box.label(text=f"Anchor: {a[0]:.0f} E, {a[1]:.0f} N", icon="PIVOT_CURSOR")
            if scene.get("terrain_object_name"):
                box.label(text=f"Terrain: {scene['terrain_object_name']}", icon="CHECKMARK")
            if scene.get("ortho_dir"):
                box.label(text="Ortho: loaded", icon="CHECKMARK")
            if scene.get("building_collection_name"):
                box.label(text=f"Buildings: {scene['building_collection_name']}", icon="CHECKMARK")


class BLENDERTOOLS_PT_tools(bpy.types.Panel):
    bl_label = "Tools"
    bl_idname = "BLENDERTOOLS_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OpenMap"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("blender_tools.cull_hidden", icon="GHOST_DISABLED")
        col.operator("blender_tools.clean_cad_mesh", icon="MESH_DATA")
        col.operator("blender_tools.compute_ndvi", icon="NODE_TEXTURE")


# ---------------------------------------------------------------------------
# Add menu
# ---------------------------------------------------------------------------

class BLENDERTOOLS_MT_main_menu(bpy.types.Menu):
    bl_idname = "BLENDERTOOLS_MT_main_menu"
    bl_label = "OpenMap Tools"

    def draw(self, context):
        layout = self.layout
        layout.operator("blender_tools.import_heightmap")
        layout.operator("blender_tools.import_ortho")
        layout.operator("blender_tools.import_buildings")
        layout.separator()
        layout.operator("blender_tools.apply_sky_preset")
        layout.operator("blender_tools.apply_ground_shader")
        layout.operator("blender_tools.scatter_trees")
        layout.separator()
        layout.operator("blender_tools.quick_scene_from_folder")


def _draw_in_add_menu(self, context):
    self.layout.separator()
    self.layout.menu(BLENDERTOOLS_MT_main_menu.bl_idname)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

CLASSES = (
    # Import
    BLENDERTOOLS_OT_import_heightmap,
    BLENDERTOOLS_OT_import_dgm5_zip,
    BLENDERTOOLS_OT_import_ortho,
    BLENDERTOOLS_OT_import_buildings,
    BLENDERTOOLS_OT_import_vdb_cloud,
    BLENDERTOOLS_OT_import_csv_path,
    # Scene Setup
    BLENDERTOOLS_OT_apply_sky_preset,
    BLENDERTOOLS_OT_apply_quality,
    BLENDERTOOLS_OT_apply_ground_shader,
    BLENDERTOOLS_OT_apply_building_textures,
    BLENDERTOOLS_OT_scatter_trees,
    BLENDERTOOLS_OT_scatter_groundcover,
    BLENDERTOOLS_OT_add_domain_cube,
    # Camera
    BLENDERTOOLS_OT_apply_camera_preset,
    BLENDERTOOLS_OT_setup_camera_rig,
    BLENDERTOOLS_OT_attach_to_path,
    # Quick Actions
    BLENDERTOOLS_OT_quick_scene_from_folder,
    BLENDERTOOLS_OT_render_preview,
    BLENDERTOOLS_OT_full_pipeline,
    # Tools
    BLENDERTOOLS_OT_cull_hidden,
    BLENDERTOOLS_OT_clean_cad_mesh,
    BLENDERTOOLS_OT_compute_ndvi,
    # Menus & Panels
    BLENDERTOOLS_MT_main_menu,
    BLENDERTOOLS_PT_import,
    BLENDERTOOLS_PT_scene_setup,
    BLENDERTOOLS_PT_camera,
    BLENDERTOOLS_PT_quick_actions,
    BLENDERTOOLS_PT_tools,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_add.append(_draw_in_add_menu)


def unregister() -> None:
    bpy.types.VIEW3D_MT_add.remove(_draw_in_add_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
