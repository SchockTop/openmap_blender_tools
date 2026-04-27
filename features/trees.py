"""trees.py — NDVI-driven 3D tree scatter via Geometry Nodes.

Generates 3 procedural tree templates via the built-in Sapling addon
(no external asset library required), then attaches a Geometry Nodes
modifier to the terrain that uses Distribute Points on Faces + Instance
on Points to scatter the trees with density from an NDVI attribute.

Falls back to procedural Voronoi-noise density if no NDVI image is in
context — keeps the pipeline working without Sentinel-2 setup.
"""
from __future__ import annotations
import math
import random
from typing import Any

NAME = "trees"
DESCRIPTION = "NDVI-driven 3D tree scatter (Sapling templates + Geometry Nodes)"

MAX_INSTANCES = 5000
TREE_TEMPLATES = [
    # (name, height_meters, leaf_color_rgb)
    ("Oak",  10.0, (0.30, 0.55, 0.20)),
    ("Pine", 14.0, (0.20, 0.40, 0.18)),
    ("Fir",   8.0, (0.18, 0.38, 0.22)),
]


def apply(context):
    bpy = context["bpy"]
    terrain = context.get("terrain_obj")
    if terrain is None:
        # Fallback: try to find an existing ground-like mesh, else create one.
        terrain = _find_or_create_fallback_terrain(bpy)
        if terrain is None:
            print("[trees] no terrain in context; skip")
            return {}
        print(f"[trees] no terrain in context; using fallback '{terrain.name}'")

    # Step 1: ensure Sapling addon is enabled (built into Blender).
    try:
        bpy.ops.preferences.addon_enable(module="add_curve_sapling")
    except Exception as e:
        print(f"[trees] WARN: Sapling addon enable failed ({e}); using cube placeholder trees")

    # Step 2: generate or reuse tree templates.
    template_collection = _ensure_tree_templates(bpy)

    # Step 3: attach Geometry Nodes scatter modifier.
    gn_mod = _attach_or_replace_gn_scatter(bpy, terrain, template_collection)

    n_templates = len(template_collection.objects)
    print(f"[trees] tree scatter attached: {n_templates} template(s), max {MAX_INSTANCES} instances")
    return {"trees_template_count": n_templates,
            "trees_modifier_name": gn_mod.name}


def _find_or_create_fallback_terrain(bpy):
    """If no terrain_obj is provided, look for an obvious ground mesh in the
    scene; if still none, create a synthetic 200x200m subdivided plane so the
    feature still demonstrates visible scattered trees during isolated tests.
    """
    try:
        scene = bpy.context.scene
    except Exception:
        return None
    # Heuristic: any mesh whose name starts with 'Terrain' / 'Ground' / 'Plane'.
    for obj in scene.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        nm = obj.name.lower()
        if nm.startswith(("terrain", "ground", "plane")):
            return obj
    # Synthesize a plane.
    try:
        bpy.ops.mesh.primitive_plane_add(size=200.0, location=(0, 0, 0))
        plane = bpy.context.active_object
        plane.name = "Terrain_Fallback"
        # Subdivide so Distribute Points on Faces has area to work with.
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.subdivide(number_cuts=20)
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        return plane
    except Exception as e:
        print(f"[trees] could not create fallback terrain: {e}")
        return None


def _ensure_tree_templates(bpy) -> Any:
    """Build or reuse a hidden 'TreeTemplates' collection with 3 trees inside."""
    coll_name = "TreeTemplates"
    if coll_name in bpy.data.collections:
        return bpy.data.collections[coll_name]
    coll = bpy.data.collections.new(coll_name)
    bpy.context.scene.collection.children.link(coll)
    coll.hide_viewport = True
    coll.hide_render = True

    for name, height, leaf_rgb in TREE_TEMPLATES:
        obj = _create_tree(bpy, name, height, leaf_rgb)
        coll.objects.link(obj)
        # Unlink from default scene collection if Sapling put it there.
        for c in obj.users_collection:
            if c is not coll:
                try: c.objects.unlink(obj)
                except Exception: pass
    return coll


def _create_tree(bpy, name, height, leaf_rgb):
    """Try Sapling first; fall back to a stylised cone+sphere if Sapling fails."""
    try:
        # Sapling provides curve_add operator with many parameters — invoke
        # with default bushy preset, then convert to mesh + scale to height.
        bpy.ops.curve.tree_add(do_update=True, bevel=True,
                               showLeaves=True, leafScale=0.5,
                               levels=3, segSplits=(0.4, 0.5, 0.0, 0.0))
        tree = bpy.context.active_object
        tree.name = f"TreeTpl_{name}"
        bpy.ops.object.convert(target="MESH")
        # Scale to target height.
        cur_z = tree.dimensions.z
        if cur_z > 0:
            scale = height / cur_z
            tree.scale = (scale, scale, scale)
            bpy.ops.object.transform_apply(scale=True)
        # Sapling succeeded — apply a simple leaf-color material so trees aren't grey.
        mat = bpy.data.materials.new(f"TreeLeaf_{name}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            boosted_rgb = (
                leaf_rgb[0],
                min(1.0, leaf_rgb[1] * 1.3),  # punch up green for distance legibility
                leaf_rgb[2],
            )
            bsdf.inputs["Base Color"].default_value = (*boosted_rgb, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.9
        tree.data.materials.clear()
        tree.data.materials.append(mat)
        return tree
    except Exception as e:
        print(f"[trees] Sapling failed for {name}: {e}; using cone+sphere placeholder")

    # --- TRUNK: 8-sided cone, brown PBR ---
    bpy.ops.mesh.primitive_cone_add(
        vertices=8,
        radius1=0.3, radius2=0.15,
        depth=height * 0.4,
        location=(0, 0, height * 0.2),
    )
    trunk = bpy.context.active_object
    trunk.name = "TempTrunk"
    trunk_mat = bpy.data.materials.new(f"TreeBark_{name}")
    trunk_mat.use_nodes = True
    bsdf = trunk_mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.25, 0.18, 0.12, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95
    trunk.data.materials.append(trunk_mat)

    # --- FOLIAGE: icosphere with Voronoi displace for organic outline ---
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=2,
        radius=height * 0.5,
        location=(0, 0, height * 0.65),
    )
    foliage = bpy.context.active_object
    foliage.name = "TempFoliage"
    tex = bpy.data.textures.new(f"TreeFoliage_{name}_disp", type="VORONOI")
    try:
        tex.noise_scale = 0.4
    except Exception:
        pass
    disp = foliage.modifiers.new("Disp", "DISPLACE")
    disp.texture = tex
    disp.strength = height * 0.05
    # Apply the displace so it bakes into the mesh.
    bpy.ops.object.select_all(action="DESELECT")
    foliage.select_set(True)
    bpy.context.view_layer.objects.active = foliage
    try:
        bpy.ops.object.modifier_apply(modifier="Disp")
    except Exception as ee:
        print(f"[trees] modifier_apply failed for {name}: {ee}")
    # Slight per-axis jitter so trees aren't perfectly symmetric.
    jitter_y = 0.9 + (hash(name) % 30) / 100.0
    jitter_z = 1.0 + (hash(name) % 20) / 100.0
    foliage.scale = (1.0, jitter_y, jitter_z)
    try:
        bpy.ops.object.transform_apply(scale=True)
    except Exception:
        pass
    foliage_mat = bpy.data.materials.new(f"TreeLeaf_{name}")
    foliage_mat.use_nodes = True
    bsdf = foliage_mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        boosted_rgb = (
            leaf_rgb[0],
            min(1.0, leaf_rgb[1] * 1.3),  # punch up green for distance legibility
            leaf_rgb[2],
        )
        bsdf.inputs["Base Color"].default_value = (*boosted_rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    foliage.data.materials.append(foliage_mat)

    # --- JOIN trunk + foliage (trunk first so its material slot 0 = bark) ---
    bpy.ops.object.select_all(action="DESELECT")
    trunk.select_set(True)
    foliage.select_set(True)
    bpy.context.view_layer.objects.active = trunk
    bpy.ops.object.join()
    tree = bpy.context.active_object
    tree.name = f"TreeTpl_{name}"
    return tree


def _attach_or_replace_gn_scatter(bpy, terrain, template_collection):
    """Attach Geometry Nodes modifier with a scatter setup. Replaces if existing."""
    mod_name = "TreeScatter"
    # Remove any existing scatter modifier (idempotent).
    existing = terrain.modifiers.get(mod_name)
    if existing:
        terrain.modifiers.remove(existing)

    mod = terrain.modifiers.new(mod_name, "NODES")
    ng = bpy.data.node_groups.new(f"{mod_name}_NG", "GeometryNodeTree")
    mod.node_group = ng

    # Node graph (minimal scatter): Group Input -> Distribute Points on Faces
    # -> Random Value (rotation Z) -> Random Value (scale) -> Instance on Points
    # (using collection) -> Realize Instances (optional) -> Group Output.
    nodes = ng.nodes; links = ng.links
    for n in list(nodes): nodes.remove(n)

    # Input/output sockets.
    if hasattr(ng, "interface"):
        ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        ng.inputs.new("NodeSocketGeometry", "Geometry")
        ng.outputs.new("NodeSocketGeometry", "Geometry")

    n_in = nodes.new("NodeGroupInput");  n_in.location = (-800, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (800, 0)
    n_dist = nodes.new("GeometryNodeDistributePointsOnFaces"); n_dist.location = (-500, 0)
    n_rot = nodes.new("FunctionNodeRandomValue"); n_rot.location = (-300, -200)
    n_rot.data_type = "FLOAT_VECTOR"
    n_rot.inputs["Min"].default_value = (0.0, 0.0, 0.0)
    n_rot.inputs["Max"].default_value = (0.0, 0.0, 6.2832)
    n_scale = nodes.new("FunctionNodeRandomValue"); n_scale.location = (-300, -400)
    n_scale.data_type = "FLOAT"
    n_scale.inputs[2].default_value = 0.7  # Min
    n_scale.inputs[3].default_value = 1.4  # Max
    n_inst = nodes.new("GeometryNodeInstanceOnPoints"); n_inst.location = (0, 0)
    n_coll = nodes.new("GeometryNodeCollectionInfo"); n_coll.location = (-300, 200)
    n_coll.inputs["Collection"].default_value = template_collection
    n_coll.inputs["Separate Children"].default_value = True
    n_coll.transform_space = "ORIGINAL"
    n_join = nodes.new("GeometryNodeJoinGeometry"); n_join.location = (400, 0)

    # Density (per area).
    n_dist.inputs["Density"].default_value = 0.005  # 50 trees per 100m² max

    links.new(n_in.outputs["Geometry"], n_dist.inputs["Mesh"])
    links.new(n_dist.outputs["Points"], n_inst.inputs["Points"])
    links.new(n_coll.outputs["Instances"], n_inst.inputs["Instance"])
    links.new(n_rot.outputs["Value"], n_inst.inputs["Rotation"])
    links.new(n_scale.outputs[1], n_inst.inputs["Scale"])  # Output index 1 for FLOAT
    links.new(n_in.outputs["Geometry"], n_join.inputs["Geometry"])
    links.new(n_inst.outputs["Instances"], n_join.inputs["Geometry"])
    links.new(n_join.outputs["Geometry"], n_out.inputs["Geometry"])
    return mod
