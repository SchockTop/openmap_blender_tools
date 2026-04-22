"""NDVI raster → Geometry-Nodes density-field configuration.

Two halves:
- compute_ndvi: shells out to GDAL's gdal_calc.py to do (NIR - R) / (NIR + R).
- ndvi_to_density_config: pure-Python helper returning a dict of GN-ready params.
"""
from __future__ import annotations

from pathlib import Path
import subprocess


def _gdal_calc_cmd(
    red_tif: Path, nir_tif: Path, output_tif: Path,
    gdal_calc_bin: str = "gdal_calc.py",
) -> list[str]:
    return [
        gdal_calc_bin,
        "-A", str(red_tif),
        "-B", str(nir_tif),
        "--outfile", str(output_tif),
        "--calc=(B.astype(float) - A.astype(float)) / (B + A + 1e-10)",
        "--NoDataValue=-9999",
        "--type=Float32",
        "--quiet",
    ]


def compute_ndvi(
    red_tif: Path, nir_tif: Path, output_tif: Path,
    gdal_calc_bin: str = "gdal_calc.py",
    timeout_seconds: int = 300,
) -> Path:
    """Compute NDVI = (NIR - R) / (NIR + R) via gdal_calc.py.

    Input bands must have matching projection + pixel grid; align first
    with gdalwarp if they don't.
    """
    cmd = _gdal_calc_cmd(red_tif, nir_tif, output_tif, gdal_calc_bin)
    subprocess.run(cmd, check=True, timeout=timeout_seconds)
    return output_tif


def ndvi_to_density_value(
    ndvi: float,
    threshold_low: float = 0.2,
    threshold_high: float = 0.8,
    max_density_per_m2: float = 0.5,
) -> float:
    """Map a single NDVI value [-1, 1] to a density-per-m² value.

    Linear interpolation between threshold_low→0 and threshold_high→max_density_per_m2.
    Clamped at the endpoints.
    """
    if ndvi <= threshold_low:
        return 0.0
    if ndvi >= threshold_high:
        return max_density_per_m2
    t = (ndvi - threshold_low) / (threshold_high - threshold_low)
    return t * max_density_per_m2


def ndvi_to_density_config(
    ndvi_tif: Path,
    uv_map_name: str = "UVMap",
    threshold_low: float = 0.2,
    threshold_high: float = 0.8,
    max_density_per_m2: float = 0.5,
    distribution_method: str = "POISSON",
) -> dict:
    """Return a dict of Geometry-Nodes configuration ready to stamp on a scatter node.

    The returned dict is plain JSON-serialisable; caller converts to GN
    inputs (Sample Image, Color Ramp, Distribute Points on Faces).

    distribution_method must be 'POISSON' or 'RANDOM' — matches Blender 5.x
    Distribute Points on Faces node's enum.
    """
    if distribution_method not in ("POISSON", "RANDOM"):
        raise ValueError(
            f"distribution_method must be POISSON or RANDOM, got {distribution_method}"
        )
    if not 0 <= threshold_low < threshold_high <= 1:
        raise ValueError(
            f"thresholds must satisfy 0 <= low < high <= 1; "
            f"got {threshold_low}, {threshold_high}"
        )
    if max_density_per_m2 <= 0:
        raise ValueError(f"max_density_per_m2 must be positive, got {max_density_per_m2}")
    return {
        "ndvi_image_path": str(Path(ndvi_tif).resolve()),
        "uv_map_name": uv_map_name,
        "color_ramp_stops": [
            {"position": threshold_low, "value": 0.0},
            {"position": threshold_high, "value": 1.0},
        ],
        "density_multiplier": max_density_per_m2,
        "distribution_method": distribution_method,
        "colorspace": "Non-Color",  # NDVI is a float value, not a colour.
        "interpolation": "Linear",  # Cubic overshoots past ±1 boundary.
    }
