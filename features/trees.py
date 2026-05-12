"""trees.py — tree scatter via Geometry Nodes, with linked TreeTemplates collection.

Loads a `TreeTemplates` collection from `assets/trees.blend` (or a per-region
override at `data/<region>/trees.blend`) using `bpy.data.libraries.load` and
attaches a Geometry Nodes scatter modifier to the terrain.

The GN graph carries a `density_mask` named-attribute hook (per-vertex float
on the terrain mesh) so scatter density can be driven from a forest-mask
GeoTIFF (OSM land-use rasterized) or an RGB greenness mask. Pass
`mask_geotiff` to `apply()` to activate this; without it the attribute
is implicitly 1.0 everywhere (unchanged behaviour, slightly lower base density).

The bundled trees.blend is built by `assets/build_trees.py` from CC0
Polyhaven sources. See assets/SOURCES.md.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

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


def apply(context, *, mask_geotiff: Optional[str] = None):
    """Scatter trees on terrain with an optional forest-density mask.

    Args:
        context: Feature context dict (must contain 'bpy'; optionally
            'terrain_obj', 'region_data_dir').
        mask_geotiff: Path to a Float32 GeoTIFF (values 0–1) that drives the
            density_mask attribute. Loaded as a Non-Color image and sampled
            through the terrain's primary UV layer. If None, density_mask
            defaults to 1.0 everywhere and the base density is used as-is.
    """
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

    mask_img = None
    if mask_geotiff:
        mask_img = _load_mask_image(bpy, mask_geotiff)

    gn_mod = _attach_or_replace_gn_scatter(bpy, terrain, coll)
    if mask_img is not None:
        _wire_mask_image(gn_mod, mask_img)
    _apply_leaf_translucency(bpy, coll)
    n = len(coll.objects)
    mask_info = f", mask={Path(mask_geotiff).name}" if mask_geotiff else ""
    print(f"[trees] linked {n} template(s) from {blend_path}, scatter attached{mask_info}")
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


def _load_mask_image(bpy, mask_geotiff: str):
    """Load a forest-mask GeoTIFF as a Non-Color image for use in the GN tree setup.

    Returns the bpy Image or None if loading fails.
    """
    img_name = "ForestMask"
    existing = bpy.data.images.get(img_name)
    if existing is not None:
        bpy.data.images.remove(existing)
    try:
        img = bpy.data.images.load(mask_geotiff)
        img.name = img_name
        img.colorspace_settings.name = "Non-Color"
        return img
    except Exception as exc:
        print(f"[trees] could not load mask GeoTIFF {mask_geotiff!r}: {exc}")
        return None


def _apply_leaf_translucency(bpy, coll) -> None:
    """Add subtle back-light translucency to leaf materials in the tree templates.

    For each material in the collection's objects that has a Principled BSDF
    with a Base Color image texture and an alpha link (i.e. a leaf card material):
    - Mix in a Translucent BSDF at ~0.15 weight so backlit forest reads as mass.
    - Idempotent: if "LeafTranslucent_Mix" output link already exists, skip.
    - Conservative: does not change Blend Method, alpha link, or roughness.
    """
    seen: set[str] = set()
    for obj in coll.objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes or mat.name in seen:
                continue
            seen.add(mat.name)
            _patch_leaf_material(bpy, mat)


def _patch_leaf_material(bpy, mat) -> None:
    """Patch a single leaf material with a subtle Translucent BSDF mix."""
    nt = mat.node_tree
    if nt is None:
        return

    # Already patched?
    if any(n.label == "LeafTranslucent_Mix" for n in nt.nodes):
        return

    # Find Principled BSDF with an image texture in Base Color and an alpha link.
    pbsdf = None
    has_alpha_link = False
    for node in nt.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        bc_socket = node.inputs.get("Base Color")
        alpha_socket = node.inputs.get("Alpha")
        if bc_socket is None:
            continue
        if not bc_socket.links:
            continue
        src = bc_socket.links[0].from_node
        if src.type != "TEX_IMAGE":
            continue
        if alpha_socket and alpha_socket.links:
            has_alpha_link = True
        pbsdf = node
        break

    if pbsdf is None or not has_alpha_link:
        return

    # Find or infer leaf color from the Base Color image node.
    base_img_node = pbsdf.inputs["Base Color"].links[0].from_node

    # Build: Translucent BSDF (uses same color) + mix with Principled at low fac.
    out_node = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out_node is None:
        return

    surface_socket = out_node.inputs.get("Surface")
    if not surface_socket or not surface_socket.links:
        return

    existing_shader = surface_socket.links[0].from_node
    existing_out_socket = surface_socket.links[0].from_socket

    transl = nt.nodes.new("ShaderNodeBsdfTranslucent")
    transl.location = (existing_shader.location.x, existing_shader.location.y - 200)
    nt.links.new(base_img_node.outputs["Color"], transl.inputs["Color"])

    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.label = "LeafTranslucent_Mix"
    mix.location = (existing_shader.location.x + 250, existing_shader.location.y - 80)
    mix.inputs["Fac"].default_value = 0.15

    nt.links.new(existing_out_socket, mix.inputs[1])
    nt.links.new(transl.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], surface_socket)


def _wire_mask_image(mod, mask_img) -> None:
    """Add image-texture sampling nodes to an existing TreeScatter GN modifier.

    Replaces the default density_mask named-attribute nodes with a chain that
    samples the forest-mask image through the terrain's primary UV layer.
    Called after _attach_or_replace_gn_scatter when a mask is provided.
    """
    ng = getattr(mod, "node_group", None)
    if ng is None:
        return
    nodes = ng.nodes
    links = ng.links

    # Find the named-attribute node that reads "density_mask" and the multiply
    # node that feeds Density.  Remove the attribute node and rewire.
    attr_node = None
    mul_node = None
    for n in nodes:
        try:
            if getattr(n, "type", "") == "INPUT_NAMED_ATTRIBUTE":
                if n.inputs["Name"].default_value == "density_mask":
                    attr_node = n
        except Exception:
            pass
        try:
            if getattr(n, "operation", "") == "MULTIPLY" and "Value" in n.outputs:
                mul_node = n
        except Exception:
            pass

    if mul_node is None:
        return  # Can't wire without the multiply node.

    if attr_node is not None:
        # Remove the old attribute link to the multiply.
        for link in list(links):
            if link.from_node is attr_node and link.to_node is mul_node:
                links.remove(link)
        nodes.remove(attr_node)

    try:
        n_uv = nodes.new("GeometryNodeInputNamedAttribute")
        n_uv.location = (-900, -150)
        n_uv.data_type = "FLOAT_VECTOR"
        n_uv.inputs["Name"].default_value = "UVMap"

        n_tex = nodes.new("GeometryNodeImageTexture")
        n_tex.location = (-720, -250)
        try:
            n_tex.inputs["Image"].default_value = mask_img
        except Exception:
            pass
        try:
            n_tex.interpolation = "Linear"
        except Exception:
            pass

        n_sep = nodes.new("ShaderNodeSeparateXYZ")
        n_sep.location = (-530, -250)

        links.new(n_uv.outputs["Attribute"], n_tex.inputs["Vector"])
        links.new(n_tex.outputs["Color"], n_sep.inputs["Vector"])
        links.new(n_sep.outputs["X"], mul_node.inputs[0])
        print("[trees] density_mask wired to forest-mask image texture")
    except Exception as exc:
        print(f"[trees] warning: could not wire mask image: {exc}")


def _attach_or_replace_gn_scatter(bpy, terrain, template_collection):
    """Attach Geometry Nodes scatter with a `density_mask` named-attribute hook.

    The density_mask attribute defaults to 1.0 everywhere. Call _wire_mask_image
    after this to replace it with a sampled GeoTIFF mask.
    """
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
    # Slightly lower base density vs the old 0.005 to avoid over-spray without a mask.
    n_mul.inputs[1].default_value = 0.004
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
