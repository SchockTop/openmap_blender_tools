"""csv_curve_import.py - generic CSV -> Bezier curve + Follow-Path attachment.

Companion to waypoints_to_camera but generalized for ANY object (cars, drones,
sensors, props) - not camera-specific. Detects WGS84 or UTM input, builds
a Bezier curve, optionally rigs an existing object to follow it.

Public API:
  read_path_csv(csv_path) -> list[dict]
  detect_coordinate_system(headers: list[str]) -> "wgs84" | "utm32n"
  csv_to_blender_curve(csv_path, anchor_utm32n, name="ImportedPath") -> bpy.types.Object
  attach_object_to_curve(obj, curve, fps=25, speed_mps=None, heading_axis="TRACK_NEGATIVE_Y") -> dict
"""
from __future__ import annotations

import csv as _csv
from pathlib import Path
from typing import Any, Optional

# Header recognition.
LAT_COLS = {"lat", "latitude", "gps_lat", "wgs84_lat"}
LON_COLS = {"lon", "lng", "longitude", "gps_lon", "wgs84_lon"}
UTM_X_COLS = {"utm_x", "easting", "e_utm32n", "x"}
UTM_Y_COLS = {"utm_y", "northing", "n_utm32n", "y"}
ALT_COLS = {"alt", "altitude", "height", "z", "elevation"}
TIME_COLS = {"time", "timestamp", "t", "time_s"}
HEADING_COLS = {"heading", "yaw", "bearing", "heading_deg"}


def detect_coordinate_system(headers: list[str]) -> str:
    h = {x.lower() for x in headers}
    has_wgs = bool(h & LAT_COLS) and bool(h & LON_COLS)
    has_utm = bool(h & UTM_X_COLS) and bool(h & UTM_Y_COLS)
    if has_wgs:
        return "wgs84"
    if has_utm:
        return "utm32n"
    raise ValueError(
        f"CSV headers {headers!r} contain neither (lat,lon) nor (utm_x,utm_y)"
    )


def _pick(row: dict, options: set[str], default=None):
    for k in row:
        if k.lower() in options:
            v = row[k]
            return v if v not in ("", None) else default
    return default


def read_path_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Read a CSV path file. Returns list of dicts with normalised keys."""
    csv_path = Path(csv_path)
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV {csv_path} has no header row")
        crs = detect_coordinate_system(reader.fieldnames)
        for raw in reader:
            entry: dict[str, Any] = {"crs": crs}
            if crs == "wgs84":
                entry["lat"] = float(_pick(raw, LAT_COLS))
                entry["lon"] = float(_pick(raw, LON_COLS))
            else:
                entry["utm_x"] = float(_pick(raw, UTM_X_COLS))
                entry["utm_y"] = float(_pick(raw, UTM_Y_COLS))
            alt = _pick(raw, ALT_COLS)
            entry["alt"] = float(alt) if alt is not None else 0.0
            t = _pick(raw, TIME_COLS)
            entry["time"] = float(t) if t is not None else None
            h = _pick(raw, HEADING_COLS)
            entry["heading"] = float(h) if h is not None else None
            rows.append(entry)
    return rows


def _wgs84_to_utm32n(lat: float, lon: float) -> tuple[float, float]:
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    return t.transform(lon, lat)


def _arc_length(points: list[tuple[float, float, float]]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        dz = points[i][2] - points[i - 1][2]
        total += (dx * dx + dy * dy + dz * dz) ** 0.5
    return total


def _require_bpy() -> Any:
    try:
        import bpy
        return bpy
    except ImportError as e:
        raise RuntimeError(
            "csv_curve_import.csv_to_blender_curve requires Blender's bpy"
        ) from e


def csv_to_blender_curve(csv_path: Path,
                         anchor_utm32n: tuple[float, float, float] = (0.0, 0.0, 0.0),
                         name: str = "ImportedPath") -> Any:
    """Read CSV + create a Bezier curve in the current Blender scene.

    Anchor-shifts to the given UTM32N origin so float32 vertex precision is
    preserved (same convention as terrain_setup).
    """
    bpy = _require_bpy()
    rows = read_path_csv(csv_path)
    if len(rows) < 2:
        raise ValueError(f"CSV {csv_path} has <2 path points; cannot build curve")

    local_pts: list[tuple[float, float, float]] = []
    for r in rows:
        if r["crs"] == "wgs84":
            x_utm, y_utm = _wgs84_to_utm32n(r["lat"], r["lon"])
        else:
            x_utm, y_utm = r["utm_x"], r["utm_y"]
        x = x_utm - anchor_utm32n[0]
        y = y_utm - anchor_utm32n[1]
        z = r["alt"] - anchor_utm32n[2]
        local_pts.append((x, y, z))

    curve_data = bpy.data.curves.new(name=f"{name}_data", type="CURVE")
    curve_data.dimensions = "3D"
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(len(local_pts) - 1)  # default has 1 already
    for i, (x, y, z) in enumerate(local_pts):
        bp = spline.bezier_points[i]
        bp.co = (x, y, z)
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    curve_obj = bpy.data.objects.new(name, curve_data)
    bpy.context.scene.collection.objects.link(curve_obj)
    curve_data.use_path = True
    return curve_obj


def attach_object_to_curve(obj: Any, curve: Any, fps: float = 25.0,
                           speed_mps: Optional[float] = None,
                           heading_axis: str = "TRACK_NEGATIVE_Y") -> dict:
    """Attach `obj` to `curve` via Follow Path constraint with optional speed.

    Args:
        obj: any bpy.types.Object (mesh, empty, camera).
        curve: bpy.types.Object of type CURVE.
        fps: scene frames per second (used to compute path_duration when
            speed_mps is given).
        speed_mps: if given, set path_duration so the object traverses the
            arc length at this speed. Else use whatever default the curve has.
        heading_axis: which axis of the object points along the path.
            Default "TRACK_NEGATIVE_Y" matches Blender's default Follow Path
            forward axis (-Y).

    Returns dict with the constraint name + computed duration.
    """
    bpy = _require_bpy()
    if curve.type != "CURVE":
        raise TypeError(f"{curve.name} is type {curve.type}, not CURVE")

    arc = 0.0
    for spline in curve.data.splines:
        pts = [(bp.co.x, bp.co.y, bp.co.z) for bp in spline.bezier_points]
        arc += _arc_length(pts)
    if speed_mps is not None and speed_mps > 0 and arc > 0:
        duration_frames = max(1, int(arc / speed_mps * fps))
        curve.data.path_duration = duration_frames
    duration = curve.data.path_duration

    con = obj.constraints.new("FOLLOW_PATH")
    con.target = curve
    con.use_curve_follow = True
    con.forward_axis = heading_axis
    con.up_axis = "UP_Z"

    curve.data.eval_time = 0.0
    curve.data.keyframe_insert("eval_time", frame=1)
    curve.data.eval_time = float(duration)
    curve.data.keyframe_insert("eval_time", frame=duration)
    if curve.data.animation_data and curve.data.animation_data.action:
        action = curve.data.animation_data.action
        # Blender <=4.x: action.fcurves; Blender 5.x: action.layers[i].strips[j].channelbag(...).fcurves
        fcurves_iter = []
        if hasattr(action, "fcurves"):
            fcurves_iter = list(action.fcurves)
        elif hasattr(action, "layers"):
            for layer in action.layers:
                for strip in layer.strips:
                    # 5.1 channelbag access varies; try slots route.
                    for slot in getattr(action, "slots", []):
                        try:
                            cb = strip.channelbag(slot)
                        except Exception:
                            cb = None
                        if cb is not None and hasattr(cb, "fcurves"):
                            fcurves_iter.extend(cb.fcurves)
        for fc in fcurves_iter:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"

    return {"constraint": con.name, "duration_frames": duration, "arc_length_m": arc}
