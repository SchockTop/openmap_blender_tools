"""geo_import.py — GDAL-based preprocessing for DGM/DOP geospatial data.

Converts Bayern LDBV DGM1/DGM5 GeoTIFFs to a 32-bit-float GeoTIFF heightmap
and splits DOP20 orthophotos into Blender UDIM tiles.

All GDAL operations are performed via the external CLI (gdalbuildvrt,
gdal_translate) through subprocess — the gdal Python binding is NOT required.

GDAL discovery order:
1. Explicit `gdal_bin` / `gdalbuildvrt_bin` arg.
2. `vendor/gdal-win64/bin/` next to this file (offline-by-default).
3. PATH lookup.

The vendored GDAL ships with PROJ database (proj.db) and GDAL CSV resources
under `vendor/gdal-win64/share/`; the helpers below set PROJ_LIB and GDAL_DATA
in the subprocess env when the vendored binaries are used.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Vendored-GDAL discovery
# ---------------------------------------------------------------------------

_VENDOR_ROOT = Path(__file__).resolve().parent / "vendor" / "gdal-win64"


def _vendored_gdal_env() -> Optional[dict[str, str]]:
    """Return an env-overlay (PROJ_LIB, GDAL_DATA, prepended PATH) for the
    bundled GDAL, or None when no vendored copy is present.
    """
    bin_dir = _VENDOR_ROOT / "bin"
    if not bin_dir.is_dir():
        # Vendored GDAL only ships for Windows; other platforms need system GDAL in PATH
        print(f"[geo_import] Vendored GDAL not found at {bin_dir}; falling back to system GDAL on PATH.")
        return None
    env = os.environ.copy()
    env["PROJ_LIB"] = str(_VENDOR_ROOT / "share" / "proj")
    env["GDAL_DATA"] = str(_VENDOR_ROOT / "share" / "gdal")
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def _resolve_gdal_bin(name: str, explicit: Optional[str] = None) -> str:
    """Resolve a GDAL CLI binary path.

    Order: explicit override → vendored copy → bare name (PATH lookup at runtime).
    `name` is e.g. "gdal_translate"; on Windows the .exe is appended automatically.
    """
    if explicit and explicit not in (name, name + ".exe"):
        return explicit
    exe_name = name + (".exe" if sys.platform == "win32" else "")
    vendored = _VENDOR_ROOT / "bin" / exe_name
    if vendored.is_file():
        return str(vendored)
    return name


# ---------------------------------------------------------------------------
# Pure-Python helpers (unit-testable without GDAL)
# ---------------------------------------------------------------------------


def udim_tile_index(u: int, v: int) -> int:
    """Return the Blender UDIM tile number for grid coordinates (u, v).

    UDIM numbering: 1001 + u + v * 10 (standard 10-wide convention).
    u must be in [0, 9]; v >= 0.

    >>> udim_tile_index(0, 0)
    1001
    >>> udim_tile_index(9, 0)
    1010
    >>> udim_tile_index(0, 1)
    1011
    """
    if not (0 <= u <= 9):
        raise ValueError(f"u must be in [0, 9], got {u}")
    if v < 0:
        raise ValueError(f"v must be >= 0, got {v}")
    return 1001 + u + v * 10


def _bbox_to_projwin_args(bbox: tuple[float, float, float, float]) -> list[str]:
    """Convert (xmin, ymin, xmax, ymax) → ['-projwin', xmin, ymax, xmax, ymin].

    GDAL's -projwin takes upper-left then lower-right: (ulx, uly, lrx, lry)
    which maps to (xmin, ymax, xmax, ymin) from a standard bbox.

    >>> _bbox_to_projwin_args((100.0, 200.0, 300.0, 400.0))
    ['-projwin', '100.0', '400.0', '300.0', '200.0']
    """
    xmin, ymin, xmax, ymax = bbox
    return ["-projwin", str(xmin), str(ymax), str(xmax), str(ymin)]


def _tile_bboxes(
    parent_bbox: tuple[float, float, float, float],
    tile_grid: tuple[int, int],
) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Return [(udim_tile_number, (xmin, ymin, xmax, ymax))] for each tile.

    Tiles are ordered row-major from bottom-left (v=0 first), matching
    Blender's UDIM convention where 1001 is the bottom-left tile.

    Args:
        parent_bbox: (xmin, ymin, xmax, ymax) of the full mosaic extent.
        tile_grid: (u_tiles, v_tiles) — number of columns and rows.

    Returns:
        List of (udim_index, bbox) tuples, length == u_tiles * v_tiles.
    """
    xmin, ymin, xmax, ymax = parent_bbox
    u_tiles, v_tiles = tile_grid

    total_width = xmax - xmin
    total_height = ymax - ymin
    tile_w = total_width / u_tiles
    tile_h = total_height / v_tiles

    result: list[tuple[int, tuple[float, float, float, float]]] = []
    for v in range(v_tiles):
        for u in range(u_tiles):
            tile_xmin = xmin + u * tile_w
            tile_ymin = ymin + v * tile_h
            tile_xmax = tile_xmin + tile_w
            tile_ymax = tile_ymin + tile_h
            udim = udim_tile_index(u % 10, v + (u // 10))
            # Standard case: u_tiles <= 10, so u is always in [0,9].
            # Recalculate correctly for grids narrower than 10:
            udim = 1001 + u + v * 10
            result.append((udim, (tile_xmin, tile_ymin, tile_xmax, tile_ymax)))

    return result


# ---------------------------------------------------------------------------
# GDAL-backed public functions
# ---------------------------------------------------------------------------


def dgm_tif_to_heightmap(
    input_tifs: list[Path],
    output_path: Path,
    bbox_utm32n: Optional[tuple[float, float, float, float]] = None,
    gdal_bin: Optional[str] = None,
    gdalbuildvrt_bin: Optional[str] = None,
) -> Path:
    """Mosaic DGM1/DGM5 GeoTIFFs and emit a 32-bit-float GeoTIFF heightmap (meters).

    Steps (all via external GDAL CLI):
    1. gdalbuildvrt -srcnodata -9999 <tmp_vrt> <input_tifs...>
    2. (optional) gdal_translate -projwin … -projwin_srs EPSG:25832 → cropped VRT.
    3. gdal_translate -ot Float32 -of GTiff -co COMPRESS=LZW -co PREDICTOR=3
       <src> <output_path>.

    Output is Float32 GeoTIFF (LZW-compressed, predictor=3 for floats). Blender's
    Image Texture node loads this natively; no EXR plugin required.

    Args:
        input_tifs: One or more DGM GeoTIFF paths.
        output_path: Destination .tif path.
        bbox_utm32n: Optional crop extent (xmin, ymin, xmax, ymax) in EPSG:25832.
        gdal_bin: Override gdal_translate executable; defaults to vendored copy
            then PATH.
        gdalbuildvrt_bin: Override gdalbuildvrt executable; same fallback.

    Returns:
        The output_path on success.

    Raises:
        subprocess.CalledProcessError: If any GDAL command fails.
        FileNotFoundError: If a GDAL binary is not found.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdal_bin = _resolve_gdal_bin("gdal_translate", gdal_bin)
    gdalbuildvrt_bin = _resolve_gdal_bin("gdalbuildvrt", gdalbuildvrt_bin)
    env = _vendored_gdal_env()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: build VRT mosaic
        vrt_path = tmp / "mosaic.vrt"
        vrt_cmd = [
            gdalbuildvrt_bin,
            "-srcnodata", "-9999",
            str(vrt_path),
        ] + [str(p) for p in input_tifs]
        subprocess.run(vrt_cmd, check=True, env=env)

        # Step 2 (optional): crop to bbox
        if bbox_utm32n is not None:
            cropped_vrt = tmp / "cropped.vrt"
            crop_cmd = [
                gdal_bin,
                "-of", "VRT",
                "-projwin_srs", "EPSG:25832",
            ] + _bbox_to_projwin_args(bbox_utm32n) + [
                str(vrt_path),
                str(cropped_vrt),
            ]
            subprocess.run(crop_cmd, check=True, env=env)
            src = cropped_vrt
        else:
            src = vrt_path

        # Step 3: convert to Float32 LZW-compressed GeoTIFF
        out_cmd = [
            gdal_bin,
            "-ot", "Float32",
            "-of", "GTiff",
            "-co", "COMPRESS=LZW",
            "-co", "PREDICTOR=3",
            "-co", "TILED=YES",
            str(src),
            str(output_path),
        ]
        subprocess.run(out_cmd, check=True, env=env)

    return output_path


# Back-compat alias (kept until call sites migrated).
dgm_tif_to_exr_heightmap = dgm_tif_to_heightmap


def dop_to_udim_tiles(
    input_orthos: list[Path],
    bbox_utm32n: tuple[float, float, float, float],
    output_dir: Path,
    tile_grid: tuple[int, int] = (10, 4),
    resolution_per_tile: int = 4096,
    gdal_bin: Optional[str] = None,
    gdalbuildvrt_bin: Optional[str] = None,
) -> list[Path]:
    """Mosaic DOP20 orthophotos and split into Blender UDIM tiles (1001..10xx).

    Naming follows Blender's convention: <output_dir>/ortho.1001.jpg,
    ortho.1002.jpg, ... numbered row-major from bottom-left per the UDIM spec
    (1001 = (0,0), 1002 = (1,0), ..., 1011 = (0,1) for a 10-wide grid).

    Args:
        input_orthos: One or more DOP orthophoto paths.
        bbox_utm32n: Crop extent (xmin, ymin, xmax, ymax) in EPSG:25832.
        output_dir: Directory where tile JPEGs will be written.
        tile_grid: (u_tiles, v_tiles) grid dimensions.
        resolution_per_tile: Output pixel size per tile (square).
        gdal_bin: Path or name of the gdal_translate executable.
        gdalbuildvrt_bin: Path or name of the gdalbuildvrt executable.

    Returns:
        List of paths to the created JPEG tiles, in UDIM order.

    Raises:
        subprocess.CalledProcessError: If any GDAL command fails.
        FileNotFoundError: If a GDAL binary is not found on PATH.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gdal_bin = _resolve_gdal_bin("gdal_translate", gdal_bin)
    gdalbuildvrt_bin = _resolve_gdal_bin("gdalbuildvrt", gdalbuildvrt_bin)
    env = _vendored_gdal_env()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: build VRT mosaic
        vrt_path = tmp / "ortho_mosaic.vrt"
        vrt_cmd = [
            gdalbuildvrt_bin,
            str(vrt_path),
        ] + [str(p) for p in input_orthos]
        subprocess.run(vrt_cmd, check=True, env=env)

        # Step 2: crop to the requested bbox
        cropped_vrt = tmp / "ortho_cropped.vrt"
        crop_cmd = [
            gdal_bin,
            "-of", "VRT",
            "-projwin_srs", "EPSG:25832",
        ] + _bbox_to_projwin_args(bbox_utm32n) + [
            str(vrt_path),
            str(cropped_vrt),
        ]
        subprocess.run(crop_cmd, check=True, env=env)

        # Step 3: export each tile
        tiles = _tile_bboxes(bbox_utm32n, tile_grid)
        output_paths: list[Path] = []

        for udim, tile_bbox in tiles:
            out_path = output_dir / f"ortho.{udim}.jpg"
            tile_cmd = [
                gdal_bin,
                "-of", "JPEG",
                "-projwin_srs", "EPSG:25832",
                "-outsize", str(resolution_per_tile), str(resolution_per_tile),
            ] + _bbox_to_projwin_args(tile_bbox) + [
                str(cropped_vrt),
                str(out_path),
            ]
            subprocess.run(tile_cmd, check=True, env=env)
            output_paths.append(out_path)

    return output_paths
