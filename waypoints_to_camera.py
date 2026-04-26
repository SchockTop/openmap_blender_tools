"""WGS84 waypoint CSV → UTM32N Bezier camera path in Blender.

Two entry points:
- wgs84_csv_to_bezier: builds the Bezier curve inside Blender.
- attach_camera_rig: attaches a Camera to the curve with Follow Path +
  Damped Track + banking driver.

Pure-Python helpers (wgs84_to_utm32n, arc_length, banking_degrees_from_curvature,
path_duration_frames) are testable without Blender or pyproj installed.

pyproj is required for wgs84_to_utm32n; guarded import.

PROJ_NETWORK=OFF is set explicitly on pyproj import so the module runs
offline even behind corporate proxies.
"""
from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Optional, Any, Sequence

# Offline-safe pyproj.
os.environ.setdefault("PROJ_NETWORK", "OFF")


# Pure-Python helpers

def read_waypoints_csv(
    csv_path: Path,
    lat_col: str = "lat",
    lon_col: str = "lon",
    alt_col: str = "alt",
) -> list[tuple[float, float, float]]:
    """Read a CSV with lat/lon/alt columns (header row required).

    Returns [(lat_deg, lon_deg, alt_m), ...] in WGS84.
    Rejects rows where any column is missing or non-numeric.
    """
    out: list[tuple[float, float, float]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {csv_path}")
        for required in (lat_col, lon_col, alt_col):
            if required not in reader.fieldnames:
                raise ValueError(
                    f"CSV missing column '{required}'; found {reader.fieldnames}"
                )
        for i, row in enumerate(reader, start=2):  # row 1 is header
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                alt = float(row[alt_col])
            except (KeyError, ValueError, TypeError) as e:
                raise ValueError(f"CSV row {i} invalid: {e}") from e
            if not -90.0 <= lat <= 90.0:
                raise ValueError(f"CSV row {i}: lat {lat} out of [-90, 90]")
            if not -180.0 <= lon <= 180.0:
                raise ValueError(f"CSV row {i}: lon {lon} out of [-180, 180]")
            out.append((lat, lon, alt))
    return out


def wgs84_to_utm32n(
    waypoints_wgs84: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """Reproject WGS84 lat/lon/alt → UTM32N E/N/alt (altitude unchanged).

    Uses pyproj.Transformer('EPSG:4326', 'EPSG:25832', always_xy=True).
    """
    try:
        from pyproj import Transformer  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "waypoints_to_camera requires pyproj. Install via "
            "`pip install -e research_bot/blender_tools`."
        ) from e
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    out: list[tuple[float, float, float]] = []
    for lat, lon, alt in waypoints_wgs84:
        # always_xy=True means .transform(lon, lat) returns (easting, northing).
        e, n = transformer.transform(lon, lat)
        out.append((float(e), float(n), float(alt)))
    return out


def subtract_anchor(
    points: list[tuple[float, float, float]],
    anchor: tuple[float, float, float],
) -> list[tuple[float, float, float]]:
    """Subtract anchor XYZ from every point. Preserves float precision."""
    ax, ay, az = anchor
    return [(p[0] - ax, p[1] - ay, p[2] - az) for p in points]


def arc_length(points: list[tuple[float, float, float]]) -> float:
    """Return the polyline arc length through the given 3D points (meters)."""
    total = 0.0
    for p0, p1 in zip(points, points[1:]):
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        total += math.sqrt(dx * dx + dy * dy + dz * dz)
    return total


def path_duration_frames(
    arc_length_m: float,
    speed_mps: float,
    fps: int,
) -> int:
    """Frames required to traverse arc_length at speed_mps @ fps. Ceiling."""
    if speed_mps <= 0:
        raise ValueError(f"speed_mps must be positive, got {speed_mps}")
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    seconds = arc_length_m / speed_mps
    return int(math.ceil(seconds * fps))


def banking_degrees_from_curvature(
    p_prev: tuple[float, float, float],
    p_curr: tuple[float, float, float],
    p_next: tuple[float, float, float],
    banking_max_deg: float = 8.0,
) -> float:
    """Estimate banking angle at p_curr based on the turn radius through the three points.

    Returns a signed angle (+ = bank right, - = bank left) clamped to ±banking_max_deg.
    Uses the signed area of the triangle / arc-length approximation for curvature.
    """
    # Edge vectors
    v_in = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
    v_out = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
    # Signed 2D cross product (curvature direction)
    cross = v_in[0] * v_out[1] - v_in[1] * v_out[0]
    # Magnitudes
    len_in = math.hypot(*v_in)
    len_out = math.hypot(*v_out)
    if len_in == 0 or len_out == 0:
        return 0.0
    # Normalised curvature proxy: sin(turn_angle)
    sin_turn = cross / (len_in * len_out)
    sin_turn = max(-1.0, min(1.0, sin_turn))
    turn_angle_deg = math.degrees(math.asin(sin_turn))
    # Scale turn angle → bank angle (empirical 0.5× multiplier for gentle banking).
    banked = turn_angle_deg * 0.5
    return max(-banking_max_deg, min(banking_max_deg, banked))


# bpy-dependent functions

def _require_bpy() -> Any:
    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "waypoints_to_camera requires Blender's bundled Python (bpy). "
            "Run via: blender --background --python <script>.py"
        ) from e
    return bpy


def wgs84_csv_to_bezier(
    csv_path: str | Path,
    anchor_utm32n: tuple[float, float, float] = (0.0, 0.0, 0.0),
    curve_name: str = "FlightPath",
    collection_name: str = "Cameras",
    fps: int = 25,
    speed_mps: float = 50.0,
) -> Any:
    """Build a Bezier curve from a WGS84 CSV in the active Blender scene."""
    bpy = _require_bpy()
    csv_path = Path(csv_path)
    waypoints_wgs84 = read_waypoints_csv(csv_path)
    waypoints_utm = wgs84_to_utm32n(waypoints_wgs84)
    waypoints_local = subtract_anchor(waypoints_utm, anchor_utm32n)
    length_m = arc_length(waypoints_local)
    duration_frames = path_duration_frames(length_m, speed_mps, fps)

    # Create curve data.
    curve_data = bpy.data.curves.new(name=curve_name, type="CURVE")
    curve_data.dimensions = "3D"
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(len(waypoints_local) - 1)
    for bp, pt in zip(spline.bezier_points, waypoints_local):
        bp.co = pt
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"

    # Curve object.
    curve_obj = bpy.data.objects.new(curve_name, curve_data)
    coll = bpy.data.collections.get(collection_name)
    if coll is None:
        coll = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(coll)
    coll.objects.link(curve_obj)

    # Path animation: set path_duration to our computed duration + force
    # linear interpolation on Evaluation Time so camera moves at constant speed.
    curve_data.path_duration = duration_frames
    curve_data.use_path = True

    # Store a custom prop for downstream tools to reuse.
    curve_obj["speed_mps"] = speed_mps
    curve_obj["arc_length_m"] = length_m

    return curve_obj


def attach_camera_rig(
    curve_obj: Any,
    camera_name: str = "FlightCamera",
    banking_max_deg: float = 8.0,
    tracked_target: Optional[Any] = None,
) -> Any:
    """Attach a Camera to the Bezier curve with Follow Path + Damped Track.

    Returns the Camera object. If tracked_target is given, the Camera uses
    Damped Track toward it; otherwise the Camera looks forward along the
    curve's tangent (set via a Track-to-Empty or None — caller's choice).
    """
    bpy = _require_bpy()

    # Empty: CamRig parent.
    rig_name = f"{camera_name}_Rig"
    rig_empty = bpy.data.objects.new(rig_name, None)
    bpy.context.scene.collection.objects.link(rig_empty)

    # Follow Path constraint on the Empty.
    follow = rig_empty.constraints.new("FOLLOW_PATH")
    follow.target = curve_obj
    follow.use_curve_follow = True

    # Camera.
    cam_data = bpy.data.cameras.new(camera_name)
    cam = bpy.data.objects.new(camera_name, cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.parent = rig_empty

    # Damped Track toward target (or identity if none).
    if tracked_target is not None:
        track = cam.constraints.new("DAMPED_TRACK")
        track.target = tracked_target
        track.track_axis = "TRACK_NEGATIVE_Z"

    # Banking driver on the rig's local Y rotation — placeholder: in a real
    # scene this driver samples curve curvature via Sample Curve GN or a
    # Python driver; for now we store the banking_max_deg as a custom prop
    # that the GN driver reads.
    rig_empty["banking_max_deg"] = banking_max_deg

    # Force constant velocity (default behaviour per cinematic playbook).
    keyframe_constant_velocity(curve_obj.data)

    return cam


def keyframe_constant_velocity(curve_data: Any) -> None:
    """Force constant velocity along a Bezier path by linear-keyframing eval_time.

    Path Animation's "Frames" slider produces ease-in/out at Bezier handles.
    Per the cinematic-camera-rig playbook §5.2, the only way to get true
    constant m/s is to keyframe Evaluation Time at frames 1 and path_duration
    with LINEAR interpolation.
    """
    duration = int(curve_data.path_duration)
    curve_data.eval_time = 0.0
    curve_data.keyframe_insert("eval_time", frame=1)
    curve_data.eval_time = float(duration)
    curve_data.keyframe_insert("eval_time", frame=duration)
    if curve_data.animation_data and curve_data.animation_data.action:
        for fc in curve_data.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
