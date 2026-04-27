"""groundcover.py — dense grass + bush scatter near camera path (low-altitude only).

Scatters thousands of small instances (grass tufts, low bushes, flowers)
high-density inside a band around the camera path or location. Outside the
band: zero density. Keeps polygon count manageable for FPV-altitude shots.

Procedural geometry — no external assets. Three primitives generated:
  - Grass tuft  (cluster of thin spikes ~0.4m tall)
  - Low bush    (icosphere with displacement noise ~0.6m)
  - Flower      (3 thin curves with a yellow/red sphere on top, ~0.3m)
"""
from __future__ import annotations
from typing import Any

NAME = "groundcover"
DESCRIPTION = "Dense grass+bush scatter in a band around the camera path (FPV-altitude only)"

VICINITY_METERS = 200.0
DEFAULT_TARGET_INSTANCES = 50_000  # target max instance count regardless of region size
DEFAULT_VICINITY_BAND = 200.0       # meters either side of the path


def _curve_arc_length(curve_obj) -> float:
    pts = []
    for spline in curve_obj.data.splines:
        for bp in (list(spline.bezier_points) + list(spline.points)):
            pts.append((bp.co.x, bp.co.y, bp.co.z))
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i-1][0]
        dy = pts[i][1] - pts[i-1][1]
        dz = pts[i][2] - pts[i-1][2]
        total += (dx*dx + dy*dy + dz*dz) ** 0.5
    return total


def _density_for_target(curve_obj, target_count: int = DEFAULT_TARGET_INSTANCES,
                        vicinity_m: float = DEFAULT_VICINITY_BAND) -> float:
    """Compute per-m² density that yields ~target_count total instances given
    the curve's arc length and the vicinity band width.

    Density = target / (arc_length × 2 × vicinity_m)

    Returns instances per m². Caps at 5.0 (sanity) and floors at 0.001
    (so big regions still get a few instances).
    """
    arc = _curve_arc_length(curve_obj)
    if arc <= 0:
        return 1.0
    band_area_m2 = arc * 2.0 * vicinity_m
    density = target_count / band_area_m2
    return max(0.001, min(5.0, density))


def apply(context):
    bpy = context["bpy"]
    terrain = context.get("terrain_obj")
    if terrain is None:
        # Try to find one (Trees feature uses similar fallback).
        for obj in bpy.data.objects:
            if obj.type == "MESH" and ("Terrain" in obj.name or "Plane" in obj.name):
                terrain = obj
                break
    if terrain is None:
        print("[groundcover] no terrain in scene; skip")
        return {}

    # Find a curve to use as scatter-vicinity center; if none, use a fake
    # 100m line at world origin (fallback "in case curve doesn't exist" -
    # the user's "with backups" requirement).
    curve = next((o for o in bpy.data.objects if o.type == "CURVE"), None)
    if curve is None:
        curve = _make_fallback_curve(bpy)

    # Auto-scale density unless overridden.
    args_ns = context.get("args")
    target = (getattr(args_ns, "groundcover_target_instances", None)
              if args_ns else None) or DEFAULT_TARGET_INSTANCES
    density = _density_for_target(curve, target_count=target)
    print(f"[groundcover] auto density {density:.4f} instances/m² "
          f"(curve arc {_curve_arc_length(curve):.0f} m, target {target} instances)")

    template_collection = _ensure_groundcover_templates(bpy)
    mod = _attach_or_replace_groundcover_gn(bpy, terrain, template_collection,
                                             curve, density=density)
    print(f"[groundcover] scatter attached: vicinity {VICINITY_METERS}m around '{curve.name}'")
    return {"groundcover_modifier_name": mod.name,
            "groundcover_template_count": len(template_collection.objects),
            "groundcover_curve_name": curve.name,
            "groundcover_density": density}


def _make_fallback_curve(bpy):
    """100m straight Bezier at world origin if no camera path exists."""
    bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, 0))
    c = bpy.context.active_object
    c.name = "GroundcoverFallbackCurve"
    spl = c.data.splines[0]
    spl.bezier_points[0].co = (-50, 0, 0)
    spl.bezier_points[1].co = (50, 0, 0)
    return c


def _ensure_groundcover_templates(bpy):
    coll_name = "GroundcoverTemplates"
    if coll_name in bpy.data.collections:
        return bpy.data.collections[coll_name]
    coll = bpy.data.collections.new(coll_name)
    bpy.context.scene.collection.children.link(coll)
    coll.hide_viewport = True
    coll.hide_render = True
    coll.objects.link(_make_grass_tuft(bpy))
    coll.objects.link(_make_low_bush(bpy))
    coll.objects.link(_make_flower(bpy))
    return coll


def _make_grass_tuft(bpy):
    """Cluster of 5 thin triangles standing up — minimal grass blade proxy."""
    import bmesh
    mesh = bpy.data.meshes.new("GroundcoverGrass")
    bm = bmesh.new()
    import random, math
    for i in range(5):
        ang = i * 2 * math.pi / 5
        x = 0.05 * math.cos(ang); y = 0.05 * math.sin(ang)
        v0 = bm.verts.new((x - 0.01, y, 0))
        v1 = bm.verts.new((x + 0.01, y, 0))
        v2 = bm.verts.new((x, y, 0.4 + random.uniform(-0.1, 0.1)))
        bm.faces.new([v0, v1, v2])
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new("GroundcoverGrass", mesh)
    obj.data.materials.append(_make_green_material(bpy, "GrassMat", (0.18, 0.4, 0.12)))
    return obj


def _make_low_bush(bpy):
    """Icosphere with displacement, ~0.6m diameter."""
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.3, location=(0, 0, 0.3))
    obj = bpy.context.active_object
    obj.name = "GroundcoverBush"
    # Apply a Displace modifier with Voronoi for organic shape.
    tex = bpy.data.textures.new("BushDisp", type="VORONOI")
    tex.noise_scale = 0.5
    disp = obj.modifiers.new("Disp", "DISPLACE")
    disp.texture = tex
    disp.strength = 0.15
    obj.data.materials.append(_make_green_material(bpy, "BushMat", (0.22, 0.36, 0.14)))
    return obj


def _make_flower(bpy):
    """3 thin spikes + yellow sphere on top, ~0.3m tall."""
    import bmesh
    mesh = bpy.data.meshes.new("GroundcoverFlower")
    bm = bmesh.new()
    for ang in (0, 2.094, 4.189):  # 0, 120, 240 deg in radians
        import math
        x = 0.02 * math.cos(ang); y = 0.02 * math.sin(ang)
        v0 = bm.verts.new((x, y, 0)); v1 = bm.verts.new((0, 0, 0.3))
        v2 = bm.verts.new((-x, -y, 0))
        bm.faces.new([v0, v1, v2])
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new("GroundcoverFlower", mesh)
    obj.data.materials.append(_make_green_material(bpy, "FlowerStem", (0.28, 0.5, 0.18)))
    return obj


def _make_green_material(bpy, name, rgb):
    if name in bpy.data.materials: return bpy.data.materials[name]
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.95
    return mat


def _attach_or_replace_groundcover_gn(bpy, terrain, template_collection, curve, density=5.0):
    mod_name = "GroundcoverScatter"
    existing = terrain.modifiers.get(mod_name)
    if existing:
        terrain.modifiers.remove(existing)
    mod = terrain.modifiers.new(mod_name, "NODES")
    ng = bpy.data.node_groups.new(f"{mod_name}_NG", "GeometryNodeTree")
    mod.node_group = ng
    nodes = ng.nodes; links = ng.links
    for n in list(nodes): nodes.remove(n)

    # Sockets.
    if hasattr(ng, "interface"):
        ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        ng.inputs.new("NodeSocketGeometry", "Geometry")
        ng.outputs.new("NodeSocketGeometry", "Geometry")

    n_in = nodes.new("NodeGroupInput");  n_in.location = (-1500, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (1200, 0)
    n_pos = nodes.new("GeometryNodeInputPosition"); n_pos.location = (-1500, -300)
    n_curve_obj = nodes.new("GeometryNodeObjectInfo"); n_curve_obj.location = (-1500, -500)
    n_curve_obj.inputs["Object"].default_value = curve
    n_curve_obj.transform_space = "RELATIVE"

    # Sample curve to get nearest distance from each terrain vertex.
    n_geom_to_curve = nodes.new("GeometryNodeProximity"); n_geom_to_curve.location = (-1100, -400)
    n_geom_to_curve.target_element = "POINTS"
    links.new(n_curve_obj.outputs["Geometry"], n_geom_to_curve.inputs["Target"])
    links.new(n_pos.outputs["Position"], n_geom_to_curve.inputs["Source Position"])

    # Mask: distance < VICINITY_METERS -> 1.0 else 0.0 (smoothstep).
    n_mask = nodes.new("ShaderNodeMath"); n_mask.location = (-700, -400)
    n_mask.operation = "LESS_THAN"
    n_mask.inputs[1].default_value = VICINITY_METERS
    links.new(n_geom_to_curve.outputs["Distance"], n_mask.inputs[0])

    # Density node.
    n_dens = nodes.new("ShaderNodeMath"); n_dens.location = (-500, -200)
    n_dens.operation = "MULTIPLY"
    n_dens.inputs[1].default_value = density   # was BASE_DENSITY
    links.new(n_mask.outputs["Value"], n_dens.inputs[0])

    # Distribute Points on Faces (with density attribute).
    n_dist = nodes.new("GeometryNodeDistributePointsOnFaces"); n_dist.location = (-200, 0)
    links.new(n_in.outputs["Geometry"], n_dist.inputs["Mesh"])
    links.new(n_dens.outputs["Value"], n_dist.inputs["Density"])

    # Random rotation + scale.
    n_rot = nodes.new("FunctionNodeRandomValue"); n_rot.location = (-200, -300)
    n_rot.data_type = "FLOAT_VECTOR"
    n_rot.inputs["Min"].default_value = (0, 0, 0)
    n_rot.inputs["Max"].default_value = (0, 0, 6.2832)
    n_scale = nodes.new("FunctionNodeRandomValue"); n_scale.location = (-200, -500)
    n_scale.data_type = "FLOAT"
    n_scale.inputs[2].default_value = 0.7
    n_scale.inputs[3].default_value = 1.3

    # Collection Info -> Instance on Points.
    n_coll = nodes.new("GeometryNodeCollectionInfo"); n_coll.location = (-200, 200)
    n_coll.inputs["Collection"].default_value = template_collection
    n_coll.inputs["Separate Children"].default_value = True
    n_coll.transform_space = "ORIGINAL"
    n_inst = nodes.new("GeometryNodeInstanceOnPoints"); n_inst.location = (200, 0)
    links.new(n_dist.outputs["Points"], n_inst.inputs["Points"])
    links.new(n_coll.outputs["Instances"], n_inst.inputs["Instance"])
    links.new(n_rot.outputs["Value"], n_inst.inputs["Rotation"])
    links.new(n_scale.outputs[1], n_inst.inputs["Scale"])

    n_join = nodes.new("GeometryNodeJoinGeometry"); n_join.location = (700, 0)
    links.new(n_in.outputs["Geometry"], n_join.inputs["Geometry"])
    links.new(n_inst.outputs["Instances"], n_join.inputs["Geometry"])
    links.new(n_join.outputs["Geometry"], n_out.inputs["Geometry"])
    return mod
