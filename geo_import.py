"""geo_import.py — GDAL-based preprocessing for DGM/DOP geospatial data.

Converts Bayern LDBV DGM1/DGM5 GeoTIFFs to a 32-bit-float EXR heightmap
and splits DOP20 orthophotos into Blender UDIM tiles.

All GDAL operations are performed via the external CLI (gdalbuildvrt,
gdal_translate) through subprocess — the gdal Python binding is NOT required.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional


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


def dgm_tif_to_exr_heightmap(
    input_tifs: list[Path],
    output_exr: Path,
    bbox_utm32n: Optional[tuple[float, float, float, float]] = None,
    gdal_bin: str = "gdal_translate",
    gdalbuildvrt_bin: str = "gdalbuildvrt",
) -> Path:
    """Mosaic DGM1/DGM5 GeoTIFFs and emit a 32-bit-float EXR heightmap in meters.

    Steps (all via external GDAL CLI):
    1. gdalbuildvrt -srcnodata -9999 <tmp_vrt> <input_tifs...>
    2. (optional) gdal_translate -projwin xmin ymax xmax ymin -projwin_srs EPSG:25832
       to crop to bbox.
    3. gdal_translate -ot Float32 -of EXR -co PIXEL_TYPE=FLOAT <src> <output_exr>.

    Args:
        input_tifs: One or more DGM GeoTIFF paths.
        output_exr: Destination path for the EXR file.
        bbox_utm32n: Optional crop extent (xmin, ymin, xmax, ymax) in EPSG:25832.
        gdal_bin: Path or name of the gdal_translate executable.
        gdalbuildvrt_bin: Path or name of the gdalbuildvrt executable.

    Returns:
        The output_exr path on success.

    Raises:
        subprocess.CalledProcessError: If any GDAL command fails.
        FileNotFoundError: If a GDAL binary is not found on PATH.
    """
    output_exr = Path(output_exr)
    output_exr.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: build VRT mosaic
        vrt_path = tmp / "mosaic.vrt"
        vrt_cmd = [
            gdalbuildvrt_bin,
            "-srcnodata", "-9999",
            str(vrt_path),
        ] + [str(p) for p in input_tifs]
        subprocess.run(vrt_cmd, check=True)

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
            subprocess.run(crop_cmd, check=True)
            src = cropped_vrt
        else:
            src = vrt_path

        # Step 3: convert to Float32 EXR
        exr_cmd = [
            gdal_bin,
            "-ot", "Float32",
            "-of", "EXR",
            "-co", "PIXEL_TYPE=FLOAT",
            str(src),
            str(output_exr),
        ]
        subprocess.run(exr_cmd, check=True)

    return output_exr


def dop_to_udim_tiles(
    input_orthos: list[Path],
    bbox_utm32n: tuple[float, float, float, float],
    output_dir: Path,
    tile_grid: tuple[int, int] = (10, 4),
    resolution_per_tile: int = 4096,
    gdal_bin: str = "gdal_translate",
    gdalbuildvrt_bin: str = "gdalbuildvrt",
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

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: build VRT mosaic
        vrt_path = tmp / "ortho_mosaic.vrt"
        vrt_cmd = [
            gdalbuildvrt_bin,
            str(vrt_path),
        ] + [str(p) for p in input_orthos]
        subprocess.run(vrt_cmd, check=True)

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
        subprocess.run(crop_cmd, check=True)

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
            subprocess.run(tile_cmd, check=True)
            output_paths.append(out_path)

    return output_paths
