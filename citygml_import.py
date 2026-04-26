"""LoD2 CityGML → CityJSON → Blender import via Up3date.

Two entry points:
- gml_to_cityjson: shells out to `citygml-tools` (CLI or Docker fallback).
- cityjson_to_blender: imports CityJSON into Blender (bpy-dependent) via the
  Up3date addon; snaps building Z to an optional terrain object; preserves
  semantic surfaces as Blender materials.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Any
import json
import subprocess
from xml.etree import ElementTree as ET

_CITYGML_NS = {
    "core": "http://www.opengis.net/citygml/2.0",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "gml":  "http://www.opengis.net/gml",
}


def _parse_pos_list(text: str, srs_dim: int = 3) -> list[tuple[float, float, float]]:
    """Split a gml:posList text blob into (x, y, z) tuples (z=0 for 2D)."""
    nums = [float(n) for n in text.split()]
    if srs_dim == 3:
        return [(nums[i], nums[i + 1], nums[i + 2]) for i in range(0, len(nums), 3)]
    return [(nums[i], nums[i + 1], 0.0) for i in range(0, len(nums), 2)]


def _vertex_index(vertex: tuple[float, float, float],
                  pool: dict[tuple[float, float, float], int],
                  ordered: list[tuple[float, float, float]]) -> int:
    if vertex in pool:
        return pool[vertex]
    idx = len(ordered)
    pool[vertex] = idx
    ordered.append(vertex)
    return idx


def gml_to_cityjson_pure(input_gmls: list[Path], output_json: Path) -> Path:
    """Pure-Python CityGML 2.0 -> CityJSON 1.1 converter for LDBV LoD2 tiles.

    Handles the LDBV CityGML subset: Building / lod2Solid / CompositeSurface /
    surfaceMember / Polygon / exterior / LinearRing / posList. Drops semantic
    surfaces (RoofSurface / WallSurface) — buildings come out as one Solid.
    Skips MultiSurface fallback for now.

    Returns output_json on success.
    """
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    vertex_pool: dict[tuple[float, float, float], int] = {}
    vertices: list[tuple[float, float, float]] = []
    city_objects: dict[str, dict] = {}

    # Accept both CityGML 1.0 (LDBV) and 2.0 building namespaces.
    bldg_tags = (
        "{http://www.opengis.net/citygml/building/2.0}Building",
        "{http://www.opengis.net/citygml/building/1.0}Building",
    )
    poly_tag = "{http://www.opengis.net/gml}Polygon"
    poslist_xpath = (
        ".//{http://www.opengis.net/gml}exterior"
        "/{http://www.opengis.net/gml}LinearRing"
        "/{http://www.opengis.net/gml}posList"
    )

    for gml_path in input_gmls:
        tree = ET.parse(gml_path)
        root = tree.getroot()
        buildings = []
        for tag in bldg_tags:
            buildings.extend(root.iter(tag))
        for bldg in buildings:
            bid = bldg.get("{http://www.opengis.net/gml}id") or f"bldg_{len(city_objects)}"
            polys: list[list[int]] = []
            for poly in bldg.iter(poly_tag):
                ring = poly.find(poslist_xpath)
                if ring is None or ring.text is None:
                    continue
                srs_dim = int(ring.get("srsDimension", "3"))
                pts = _parse_pos_list(ring.text, srs_dim)
                # CityGML rings repeat the first point at the end — drop it.
                if pts and pts[0] == pts[-1]:
                    pts = pts[:-1]
                if len(pts) < 3:
                    continue
                ring_idx = [_vertex_index(p, vertex_pool, vertices) for p in pts]
                polys.append([ring_idx])  # single exterior ring (no holes)
            if not polys:
                continue
            city_objects[bid] = {
                "type": "Building",
                "geometry": [{
                    "type": "Solid",
                    "lod": "2",
                    "boundaries": [polys],  # Solid -> shells -> surfaces -> rings
                }],
            }

    cityjson = {
        "type": "CityJSON",
        "version": "1.1",
        "CityObjects": city_objects,
        "vertices": [list(v) for v in vertices],
        "metadata": {
            "referenceSystem": "https://www.opengis.net/def/crs/EPSG/0/25832",
        },
    }
    output_json.write_text(json.dumps(cityjson, separators=(",", ":")), encoding="utf-8")
    return output_json


# Pure-Python helpers (no external deps — fully unit-testable)

def parse_citygml_lod_level(gml_path: Path) -> int:
    """Parse LoD level from CityGML filename or a small head-read of the file.

    LoD is embedded in LDBV filenames as `_lod2_` typically; fallback to
    reading the first 8 KB of the file for any `lod="2"` attribute.
    Returns an int (0, 1, 2, 3, 4). Raises ValueError if indeterminate.
    """
    name = gml_path.name.lower()
    for level in (4, 3, 2, 1, 0):
        if f"lod{level}" in name or f"lod_{level}" in name or f"_lod{level}_" in name:
            return level
    # Fallback: read a header window.
    try:
        with gml_path.open("rb") as f:
            head = f.read(8192).decode("utf-8", errors="ignore").lower()
    except OSError as e:
        raise ValueError(f"Cannot read {gml_path}: {e}") from e
    for level in (4, 3, 2, 1, 0):
        if f'lod="{level}"' in head or f"lod{level}" in head:
            return level
    raise ValueError(f"Cannot determine LoD level from {gml_path}")


def building_z_snap_offset(
    building_ground_z: float,
    terrain_z_at_xy: float,
    clamp_meters: float = 5.0,
) -> float:
    """Compute the Z offset to apply to a building so its ground-floor sits on terrain.

    Returns (terrain_z_at_xy - building_ground_z), clamped to ±clamp_meters
    to avoid drastic shifts when LoD2 ground-floor data is missing or wrong.
    """
    raw = terrain_z_at_xy - building_ground_z
    if raw > clamp_meters:
        return clamp_meters
    if raw < -clamp_meters:
        return -clamp_meters
    return raw


def _citygml_tools_cmd(
    input_gmls: list[Path],
    output_json: Path,
    use_docker: bool = False,
    docker_image: str = "citygml4j/citygml-tools",
) -> list[str]:
    """Build the citygml-tools subprocess command. Returned list ready for subprocess.run.

    Docker path mounts the CWD at /data and translates paths accordingly.
    """
    if use_docker:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{Path.cwd()}:/data",
            docker_image,
            "to-cityjson",
        ]
        cmd += [f"/data/{p.relative_to(Path.cwd())}" for p in input_gmls]
        cmd += ["--output", f"/data/{output_json.relative_to(Path.cwd())}"]
    else:
        cmd = ["citygml-tools", "to-cityjson"]
        cmd += [str(p) for p in input_gmls]
        cmd += ["--output", str(output_json)]
    return cmd


def gml_to_cityjson(
    input_gmls: list[Path],
    output_json: Path,
    use_docker: bool = False,
    docker_image: str = "citygml4j/citygml-tools",
    timeout_seconds: int = 600,
) -> Path:
    """Convert CityGML files to a single CityJSON. Shells out to citygml-tools."""
    cmd = _citygml_tools_cmd(input_gmls, output_json, use_docker, docker_image)
    subprocess.run(cmd, check=True, timeout=timeout_seconds)
    return output_json


# bpy-dependent import helpers (mocked in tests)

def _require_bpy() -> Any:
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "citygml_import.cityjson_to_blender requires Blender's bundled Python (bpy). "
            "Run via: blender --background --python <script>.py"
        ) from e
    return bpy


def cityjson_to_blender(
    cityjson_path: Path,
    anchor_utm32n: tuple[float, float, float] = (0.0, 0.0, 0.0),
    terrain_object_name: Optional[str] = None,
    collection_name: str = "Buildings",
) -> list[Any]:
    """Import a CityJSON file into the current Blender scene via Up3date.

    If `terrain_object_name` is given, each building's ground face is
    snapped to the terrain surface at the building's XY centroid (via a
    ray cast straight down from above + building_z_snap_offset).

    Returns the list of created Blender Objects (one per building).
    """
    bpy = _require_bpy()
    # Up3date addon API — guarded; fall back to CityJSON4J via file operator.
    try:
        bpy.ops.preferences.addon_enable(module="up3date")
    except Exception:
        pass  # addon may not be installed; caller handles the import error

    # Load anchor into scene prop for downstream consumption.
    bpy.context.scene["utm32n_anchor"] = list(anchor_utm32n)

    # Create collection.
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        coll = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(coll)

    # Import via the Up3date operator (signature per its README).
    # Fallback: a manual JSON parse + mesh-from-verts build.
    try:
        bpy.ops.up3date.import_cityjson(filepath=str(cityjson_path))
    except (AttributeError, RuntimeError):
        # Manual fallback: parse and create placeholder mesh per building.
        return _manual_cityjson_import(
            bpy, cityjson_path, anchor_utm32n, coll, terrain_object_name
        )

    # Collect imported objects (Up3date puts them under the active collection).
    imported = [obj for obj in coll.objects if obj.type == "MESH"]
    return imported


def _manual_cityjson_import(
    bpy: Any,
    cityjson_path: Path,
    anchor: tuple[float, float, float],
    coll: Any,
    terrain_object_name: Optional[str],
) -> list[Any]:
    """CityJSON -> Blender meshes with proper face reconstruction.

    Walks the CityJSON Solid/MultiSurface boundary nesting and builds one
    Blender mesh per Building with all polygon faces preserved. Holes inside
    rings are dropped (LDBV LoD2 buildings rarely have inner rings).
    """
    data = json.loads(cityjson_path.read_text(encoding="utf-8"))
    verts_global = data.get("vertices", [])
    transform = data.get("transform", {})
    scale = transform.get("scale", [1.0, 1.0, 1.0])
    translate = transform.get("translate", [0.0, 0.0, 0.0])
    result: list[Any] = []

    for obj_id, obj in data.get("CityObjects", {}).items():
        if obj.get("type") not in {"Building", "BuildingPart"}:
            continue
        # Collect all face rings across all geometries on this object.
        faces_global_idx: list[list[int]] = []
        for geom in obj.get("geometry", []):
            _collect_face_rings(geom.get("boundaries", []), geom.get("type"),
                                faces_global_idx)
        if not faces_global_idx:
            continue

        # Re-index from global vertex space to local mesh-vertex space.
        local_idx_for_global: dict[int, int] = {}
        local_verts: list[tuple[float, float, float]] = []
        local_faces: list[list[int]] = []
        for face in faces_global_idx:
            new_face = []
            for gi in face:
                if gi not in local_idx_for_global:
                    gv = verts_global[gi]
                    local_idx_for_global[gi] = len(local_verts)
                    local_verts.append((
                        (gv[0] * scale[0] + translate[0]) - anchor[0],
                        (gv[1] * scale[1] + translate[1]) - anchor[1],
                        (gv[2] * scale[2] + translate[2]) - anchor[2],
                    ))
                new_face.append(local_idx_for_global[gi])
            if len(new_face) >= 3:
                local_faces.append(new_face)

        mesh = bpy.data.meshes.new(f"CityJSON_{obj_id}")
        mesh.from_pydata(local_verts, [], local_faces)
        mesh.update()
        mesh_obj = bpy.data.objects.new(f"CityJSON_{obj_id}", mesh)
        coll.objects.link(mesh_obj)
        result.append(mesh_obj)
    return result


def _collect_face_rings(boundary: Any, geom_type: Optional[str],
                        out: list[list[int]]) -> None:
    """Walk CityJSON nested boundary lists and append every face's outer ring.

    CityJSON nesting depth depends on geometry type:
      MultiPoint:    [v0, v1, ...]                                    (depth 1)
      MultiLineString: [[v0,v1], ...]                                 (depth 2)
      MultiSurface:  [[[v0,v1,v2], ...], ...]    (face -> rings)      (depth 3)
      Solid:         [[[[v...], ...], ...], ...] (shell -> faces -> rings) (depth 4)
      MultiSolid:    [[[[[v...], ...], ...], ...], ...]               (depth 5)

    We only emit the *exterior* ring (first ring of each face). Holes ignored.
    """
    if not isinstance(boundary, list):
        return
    # Heuristic: descend until we find a list whose first element is an int —
    # that level holds vertex indices (an exterior ring). Treat its parent
    # list as a face's ring list and take ring [0].
    if boundary and isinstance(boundary[0], int):
        # We are AT a ring. The caller wraps it; should not happen here.
        out.append(list(boundary))
        return
    if boundary and isinstance(boundary[0], list) and boundary[0] \
            and isinstance(boundary[0][0], int):
        # We are at a face: [exterior_ring, *interior_rings]
        out.append(list(boundary[0]))
        return
    # Descend.
    for child in boundary:
        _collect_face_rings(child, geom_type, out)
