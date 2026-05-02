"""trees.py — tree scatter via Geometry Nodes, with linked TreeTemplates collection.

Loads a `TreeTemplates` collection from `assets/trees.blend` (or a per-region
override at `data/<region>/trees.blend`) using `bpy.data.libraries.load` and
attaches a Geometry Nodes scatter modifier to the terrain.

The GN graph carries a `density_mask` named-attribute hook (per-vertex float
on the terrain mesh) so future work can drive scatter density from OSM
landuse polygons. Currently the attribute is implicitly 1.0 everywhere.

The bundled trees.blend is built by `assets/build_trees.py` from CC0
Polyhaven sources. See assets/SOURCES.md.
"""
from __future__ import annotations
from pathlib import Path

NAME = "trees"
DESCRIPTION = "Linked tree templates + Geometry Nodes scatter with density_mask hook"


def _bundled_trees_blend() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "trees.blend"


def _resolve_trees_blend(region_data_dir) -> Path:
    """Per-region override beats the bundled default."""
    if region_data_dir:
        candidate = Path(region_data_dir) / "trees.blend"
        if candidate.exists():
            return candidate
    return _bundled_trees_blend()


def apply(context):
    bpy = context["bpy"]
    terrain = context.get("terrain_obj")
    if terrain is None:
        terrain = _find_or_create_fallback_terrain(bpy)
        if terrain is None:
            print("[trees] no terrain in context; skip")
            return {}
        print(f"[trees] using fallback terrain '{terrain.name}'")

    blend_path = _resolve_trees_blend(context.get("region_data_dir"))
    coll = _ensure_tree_templates(bpy, blend_path)
    if coll is None or not coll.objects:
        print(f"[trees] could not load TreeTemplates from {blend_path}; skip")
        return {}

    gn_mod = _attach_or_replace_gn_scatter(bpy, terrain, coll)
    n = len(coll.objects)
    print(f"[trees] linked {n} template(s) from {blend_path}, scatter attached")
    return {"trees_template_count": n,
            "trees_modifier_name": gn_mod.name,
            "trees_blend_source": str(blend_path)}


def _find_or_create_fallback_terrain(bpy):
    try:
        scene = bpy.context.scene
    except Exception:
        return None
    for obj in scene.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        nm = obj.name.lower()
        if nm.startswith(("terrain", "ground", "plane")):
            return obj
    try:
        bpy.ops.mesh.primitive_plane_add(size=200.0, location=(0, 0, 0))
        plane = bpy.context.active_object
        plane.name = "Terrain_Fallback"
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.subdivide(number_cuts=20)
        bpy.ops.object.mode_set(mode="OBJECT")
        return plane
    except Exception:
        return None


def _ensure_tree_templates(bpy, blend_path=None):
    """Load (append) the TreeTemplates collection from the given .blend.

    Append (not link) so the collection lives in the resulting scene .blend
    even if the source file moves. Idempotent: if TreeTemplates is already
    present in the scene, returns it.

    Backwards-compat: callers without a path use the bundled one. Old tests
    that monkeypatch this function still work.
    """
    coll_name = "TreeTemplates"
    if coll_name in bpy.data.collections:
        return bpy.data.collections[coll_name]

    if blend_path is None:
        blend_path = _bundled_trees_blend()

    with bpy.data.libraries.load(str(blend_path), link=False) as (data_from, data_to):
        if coll_name not in data_from.collections:
            return None
        data_to.collections = [coll_name]

    coll = bpy.data.collections.get(coll_name)
    if coll is not None:
        try:
            bpy.context.scene.collection.children.link(coll)
        except Exception:
            pass
        coll.hide_viewport = True
        coll.hide_render = True
    return coll


def _attach_or_replace_gn_scatter(bpy, terrain, template_collection):
    """Attach Geometry Nodes scatter with a `density_mask` attribute hook."""
    mod_name = "TreeScatter"
    existing = terrain.modifiers.get(mod_name)
    if existing:
        terrain.modifiers.remove(existing)

    mod = terrain.modifiers.new(mod_name, "NODES")
    ng = bpy.data.node_groups.new(f"{mod_name}_NG", "GeometryNodeTree")
    mod.node_group = ng

    nodes = ng.nodes; links = ng.links
    for n in list(nodes): nodes.remove(n)

    if hasattr(ng, "interface"):
        ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        ng.inputs.new("NodeSocketGeometry", "Geometry")
        ng.outputs.new("NodeSocketGeometry", "Geometry")

    n_in = nodes.new("NodeGroupInput");  n_in.location = (-1000, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (1000, 0)
    n_dist = nodes.new("GeometryNodeDistributePointsOnFaces"); n_dist.location = (-500, 0)

    # density_mask hook (per-vertex float; 1.0 everywhere by default).
    n_attr = nodes.new("GeometryNodeInputNamedAttribute"); n_attr.location = (-800, -300)
    n_attr.data_type = "FLOAT"
    n_attr.inputs["Name"].default_value = "density_mask"
    n_mul = nodes.new("ShaderNodeMath"); n_mul.location = (-600, -300)
    n_mul.operation = "MULTIPLY"
    n_mul.inputs[1].default_value = 0.005  # base density
    links.new(n_attr.outputs["Attribute"], n_mul.inputs[0])
    links.new(n_mul.outputs["Value"], n_dist.inputs["Density"])

    n_rot = nodes.new("FunctionNodeRandomValue"); n_rot.location = (-300, -200)
    n_rot.data_type = "FLOAT_VECTOR"
    n_rot.inputs["Min"].default_value = (0.0, 0.0, 0.0)
    n_rot.inputs["Max"].default_value = (0.0, 0.0, 6.2832)
    n_scale = nodes.new("FunctionNodeRandomValue"); n_scale.location = (-300, -400)
    n_scale.data_type = "FLOAT"
    n_scale.inputs[2].default_value = 0.7
    n_scale.inputs[3].default_value = 1.4
    n_inst = nodes.new("GeometryNodeInstanceOnPoints"); n_inst.location = (0, 0)
    n_coll = nodes.new("GeometryNodeCollectionInfo"); n_coll.location = (-300, 200)
    n_coll.inputs["Collection"].default_value = template_collection
    n_coll.inputs["Separate Children"].default_value = True
    n_coll.transform_space = "ORIGINAL"
    n_join = nodes.new("GeometryNodeJoinGeometry"); n_join.location = (400, 0)

    links.new(n_in.outputs["Geometry"], n_dist.inputs["Mesh"])
    links.new(n_dist.outputs["Points"], n_inst.inputs["Points"])
    links.new(n_coll.outputs["Instances"], n_inst.inputs["Instance"])
    links.new(n_rot.outputs["Value"], n_inst.inputs["Rotation"])
    links.new(n_scale.outputs[1], n_inst.inputs["Scale"])
    links.new(n_in.outputs["Geometry"], n_join.inputs["Geometry"])
    links.new(n_inst.outputs["Instances"], n_join.inputs["Geometry"])
    links.new(n_join.outputs["Geometry"], n_out.inputs["Geometry"])
    return mod
