"""waypoint_generators.py - per-preset waypoint CSV generators.

Each generator takes a UTM32N bbox + altitude + n_points and returns a list
of (lat, lon, alt) tuples ready to write to a waypoints CSV consumed by
wgs84_csv_to_bezier.

Picked by name via generate_waypoints_for_preset(preset_name, bbox, ...).
Falls back to a generic S-curve if preset is unknown.
"""
from __future__ import annotations
import math
from typing import Callable

# Lazy pyproj import - only needed when generating real waypoints.

def _utm_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """UTM32N (x, y) -> (lat, lon)."""
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    lon, lat = t.transform(x, y)
    return (lat, lon)


def s_curve_diagonal(bbox: tuple[float, float, float, float],
                     altitude_agl_m: float,
                     n_points: int = 30) -> list[tuple[float, float, float]]:
    """Generic S-curve from west to east with sinusoidal Y. Default fallback."""
    xmin, ymin, xmax, ymax = bbox
    pts = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        x = xmin + (xmax - xmin) * frac
        y = ymin + (ymax - ymin) * (0.5 + 0.4 * math.sin(frac * math.pi * 2))
        lat, lon = _utm_to_wgs84(x, y)
        pts.append((lat, lon, altitude_agl_m))
    return pts


def ground_snake(bbox, altitude_agl_m, n_points=30):
    """Tight slow snake through the bbox center, 300m total."""
    xmin, ymin, xmax, ymax = bbox
    cx = (xmin + xmax) / 2; cy = (ymin + ymax) / 2
    pts = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        # 300m snake: 150m east-west sinusoidal, 75m north-south sinusoidal
        x = cx + 150.0 * math.cos(frac * math.pi * 2) - 150.0 * (1 - frac * 2 if frac < 0.5 else 2 * frac - 1)
        y = cy + 75.0 * math.sin(frac * math.pi * 4)
        lat, lon = _utm_to_wgs84(x, y)
        pts.append((lat, lon, altitude_agl_m))
    return pts


def straight_through(bbox, altitude_agl_m, n_points=30):
    """Straight line through bbox center, axis-aligned."""
    xmin, ymin, xmax, ymax = bbox
    cy = (ymin + ymax) / 2
    pts = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        x = xmin + (xmax - xmin) * frac
        lat, lon = _utm_to_wgs84(x, cy)
        pts.append((lat, lon, altitude_agl_m))
    return pts


def orbit_around_center(bbox, altitude_agl_m, n_points=60):
    """Single circular orbit around bbox center, radius = min half-extent."""
    xmin, ymin, xmax, ymax = bbox
    cx = (xmin + xmax) / 2; cy = (ymin + ymax) / 2
    radius = min(xmax - xmin, ymax - ymin) * 0.4
    pts = []
    for i in range(n_points):
        ang = i * 2 * math.pi / (n_points - 1)
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        lat, lon = _utm_to_wgs84(x, y)
        pts.append((lat, lon, altitude_agl_m))
    return pts


def banking_diagonal(bbox, altitude_agl_m, n_points=40):
    """Long diagonal corner-to-corner with banking S-curve halfway."""
    xmin, ymin, xmax, ymax = bbox
    pts = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        # Diagonal NW corner to SE corner with sin curve mid-flight.
        x = xmin + (xmax - xmin) * frac
        y_lin = ymax - (ymax - ymin) * frac
        y = y_lin + (ymax - ymin) * 0.15 * math.sin(frac * math.pi)
        lat, lon = _utm_to_wgs84(x, y)
        pts.append((lat, lon, altitude_agl_m))
    return pts


def descending_approach(bbox, altitude_agl_m, n_points=40,
                        descent_factor: float = 0.5):
    """Straight line from far edge with descending altitude."""
    xmin, ymin, xmax, ymax = bbox
    cy = (ymin + ymax) / 2
    # Extend start point 4 km beyond bbox west edge.
    x_start = xmin - 4000.0
    x_end = xmax
    pts = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        x = x_start + (x_end - x_start) * frac
        # Altitude descends linearly from altitude_agl_m to altitude_agl_m * descent_factor.
        alt = altitude_agl_m * (1.0 - frac * (1.0 - descent_factor))
        lat, lon = _utm_to_wgs84(x, cy)
        pts.append((lat, lon, alt))
    return pts


# Registry: preset name -> generator function.
PRESET_GENERATORS: dict[str, Callable] = {
    "fpv-walk":               ground_snake,
    "fpv-bike":               straight_through,
    "low-drone":              orbit_around_center,
    "mid-drone":              s_curve_diagonal,
    "cinematic-establishing": banking_diagonal,
    "aircraft-approach":      descending_approach,
}


def generate_waypoints_for_preset(preset_name: str,
                                  bbox: tuple[float, float, float, float],
                                  altitude_agl_m: float | None = None,
                                  n_points: int | None = None,
                                  ) -> list[tuple[float, float, float]]:
    """Pick a generator by preset name; fall back to s_curve_diagonal if unknown.

    altitude_agl_m comes from the preset if not specified.
    n_points uses the generator's default if not specified.
    """
    if altitude_agl_m is None:
        # Pull from camera_presets if available.
        try:
            from .camera_presets import get_preset
            altitude_agl_m = float(get_preset(preset_name)["altitude_agl_m"])
        except Exception:
            altitude_agl_m = 1500.0
    gen = PRESET_GENERATORS.get(preset_name, s_curve_diagonal)
    if n_points is None:
        return gen(bbox, altitude_agl_m)
    return gen(bbox, altitude_agl_m, n_points)
