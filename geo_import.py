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


def geotiff_metadata(tif_path: Path) -> dict:
    """Read GeoTIFF size and geo-extent via gdalinfo (no PIL/rasterio needed).

    Returns dict with keys: width, height, pixel_x, pixel_y, origin_x, origin_y,
    size_meters_x, size_meters_y.
    """
    import json as _json
    gdalinfo_bin = _resolve_gdal_bin("gdalinfo")
    env = _vendored_gdal_env()
    raw = subprocess.check_output(
        [gdalinfo_bin, "-json", str(tif_path)],
        env=env, stderr=subprocess.DEVNULL,
    )
    info = _json.loads(raw)
    w, h = info["size"]
    gt = info.get("geoTransform", [0, 1, 0, 0, 0, -1])
    pixel_x = abs(gt[1])
    pixel_y = abs(gt[5])
    origin_x = gt[0]
    origin_y = gt[3]
    return {
        "width": w, "height": h,
        "pixel_x": pixel_x, "pixel_y": pixel_y,
        "origin_x": origin_x, "origin_y": origin_y,
        "size_meters_x": w * pixel_x,
        "size_meters_y": h * pixel_y,
    }


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


def dgm5_xyz_to_geotiffs(
    zip_paths: list[Path],
    out_dir: Path,
    srs: str = "EPSG:25832",
    gdal_bin: Optional[str] = None,
) -> list[Path]:
    """Extract DGM5 XYZ-ASCII .zip archives and convert each to GeoTIFF.

    Bayern serves DGM5 as zipped XYZ text files (space-separated
    ``easting northing elevation``).  GDAL's XYZ driver reads these
    natively; we just need to unzip first, then ``gdal_translate``.

    Args:
        zip_paths: .zip files, each containing one .txt/.xyz ASCII grid.
        out_dir: Directory for the output GeoTIFFs.
        srs: Spatial reference to assign (the XYZ files have no CRS header).
        gdal_bin: Override for ``gdal_translate``; defaults to vendored copy.

    Returns:
        List of output .tif paths (one per input zip).
    """
    import zipfile

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gdal_bin = _resolve_gdal_bin("gdal_translate", gdal_bin)
    env = _vendored_gdal_env()
    result: list[Path] = []

    for zp in zip_paths:
        zp = Path(zp)
        if not zp.is_file():
            print(f"[dgm5] warning: {zp} not found, skipping", file=sys.stderr)
            continue
        with zipfile.ZipFile(zp) as zf:
            txt_names = [n for n in zf.namelist()
                         if n.lower().endswith((".txt", ".xyz"))]
            if not txt_names:
                print(f"[dgm5] warning: no .txt/.xyz in {zp.name}, skipping",
                      file=sys.stderr)
                continue
            for txt_name in txt_names:
                extracted = Path(zf.extract(txt_name, out_dir))
                out_tif = out_dir / (extracted.stem + ".tif")
                cmd = [
                    gdal_bin,
                    "-a_srs", srs,
                    "-ot", "Float32",
                    "-of", "GTiff",
                    "-co", "COMPRESS=LZW",
                    "-co", "PREDICTOR=3",
                    "-co", "TILED=YES",
                    str(extracted),
                    str(out_tif),
                ]
                subprocess.run(cmd, check=True, env=env)
                extracted.unlink()
                result.append(out_tif)
                print(f"[dgm5] {zp.name}/{txt_name} -> {out_tif.name}")

    return result


def _is_forest_feature(props: dict) -> bool:
    """Return True if a GeoJSON feature's properties describe a forest/wood polygon.

    Matches OSM landuse=forest, landuse=wood, natural=wood, and natural=scrub.
    Pure-Python — no GDAL dependency.

    >>> _is_forest_feature({"landuse": "forest"})
    True
    >>> _is_forest_feature({"landuse": "residential"})
    False
    >>> _is_forest_feature({"natural": "wood"})
    True
    >>> _is_forest_feature({"natural": "water"})
    False
    >>> _is_forest_feature({})
    False
    """
    lu = props.get("landuse", "")
    nat = props.get("natural", "")
    return lu in ("forest", "wood") or nat in ("wood", "scrub")


def _exg_formula(r: float, g: float, b: float) -> float:
    """Compute Excess Green (ExG) index from normalised R, G, B values.

    ExG = 2*G - R - B, then normalise from [-1, 2] → [0, 1].
    Values above threshold ~0.1 indicate green (vegetated) pixels.

    >>> round(_exg_formula(0.0, 1.0, 0.0), 4)
    1.0
    >>> round(_exg_formula(1.0, 0.0, 0.0), 4)
    0.0
    """
    raw = 2.0 * g - r - b  # range [-2, 2], in practice [-1, 2]
    return max(0.0, min(1.0, (raw + 1.0) / 3.0))


def rasterize_forest_mask(
    landuse_geojson: str,
    ref_geotiff: str,
    out_path: str,
    gdal_bin: Optional[str] = None,
    gdalbuildvrt_bin: Optional[str] = None,
) -> str:
    """Rasterize OSM land-use forest polygons onto the grid of a reference GeoTIFF.

    Filters GeoJSON features where landuse=forest/wood OR natural=wood/scrub,
    then burns 1.0 (Float32) on forest cells and 0.0 elsewhere, matching extent
    + resolution of ref_geotiff exactly.

    Strategy:
    1. If gdal_rasterize is available (system GDAL), delegate to it (highest quality,
       handles reprojection).
    2. Otherwise fall back to a numpy-based rasterizer that handles WGS84 GeoJSON on
       a UTM-projected (EPSG:25832) reference raster by converting polygon coordinates
       via pyproj (if available) or treating them as-is (if already in the same CRS).
       Requires numpy.

    Args:
        landuse_geojson: Path to an OSM land_use.geojson (from OSMDownloader).
        ref_geotiff: Path to the reference heightmap GeoTIFF (sets extent + grid).
        out_path: Output Float32 GeoTIFF path.
        gdal_bin: Override for gdal_rasterize; defaults to PATH lookup.
        gdalbuildvrt_bin: Unused; kept for API consistency.

    Returns:
        out_path on success.

    Raises:
        RuntimeError: If neither gdal_rasterize nor numpy is available.
        subprocess.CalledProcessError: If gdal_rasterize subprocess fails.
    """
    import json as _json

    out_path_obj = Path(out_path)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)

    gdalinfo_bin = _resolve_gdal_bin("gdalinfo")
    env = _vendored_gdal_env()

    # Read and filter the GeoJSON to forest/wood features only.
    with open(landuse_geojson, encoding="utf-8") as fh:
        fc = _json.load(fh)

    forest_features = [
        f for f in fc.get("features", [])
        if _is_forest_feature(f.get("properties") or {})
    ]

    if not forest_features:
        print(f"[geo_import] rasterize_forest_mask: no forest features found in {landuse_geojson}")

    # Read reference raster extent and size.
    raw = subprocess.check_output(
        [gdalinfo_bin, "-json", str(ref_geotiff)],
        env=env, stderr=subprocess.DEVNULL,
    )
    info = _json.loads(raw)
    w, h = info["size"]
    gt = info.get("geoTransform", [0, 1, 0, 0, 0, -1])
    origin_x, pixel_x = gt[0], abs(gt[1])
    origin_y, pixel_y = gt[3], abs(gt[5])

    # Try gdal_rasterize from PATH (not vendored — vendored set only has translate/buildvrt/info).
    import shutil as _shutil
    gdal_rasterize_path = _shutil.which("gdal_rasterize")

    if gdal_rasterize_path:
        _rasterize_forest_gdal(
            forest_features, ref_geotiff, out_path_obj,
            gdal_rasterize_path, w, h, origin_x, origin_y, pixel_x, pixel_y, env,
        )
    else:
        _rasterize_forest_numpy(
            forest_features, out_path_obj,
            w, h, origin_x, origin_y, pixel_x, pixel_y,
        )

    n = len(forest_features)
    print(f"[geo_import] rasterize_forest_mask: burned {n} forest feature(s) -> {out_path_obj.name}")
    return str(out_path_obj)


def _rasterize_forest_gdal(
    forest_features: list,
    ref_geotiff: str,
    out_path: Path,
    gdal_rasterize: str,
    w: int, h: int,
    origin_x: float, origin_y: float, pixel_x: float, pixel_y: float,
    env: Optional[dict],
) -> None:
    """Burn forest polygons via gdal_rasterize (requires gdal_rasterize on PATH)."""
    import json as _json
    import shutil as _shutil

    xmin = origin_x; ymax = origin_y
    xmax = origin_x + w * pixel_x; ymin = origin_y - h * pixel_y

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        filtered_path = tmp / "forest_only.geojson"
        filtered_fc = {"type": "FeatureCollection", "features": forest_features}
        filtered_path.write_text(_json.dumps(filtered_fc), encoding="utf-8")

        blank_path = tmp / "blank.tif"
        create_cmd = [
            _resolve_gdal_bin("gdal_translate"),
            "-of", "GTiff", "-ot", "Float32",
            "-co", "COMPRESS=LZW",
            "-scale", "0", "1", "0", "0",
            "-outsize", str(w), str(h),
        ] + _bbox_to_projwin_args((xmin, ymin, xmax, ymax)) + [
            "-projwin_srs", "EPSG:25832",
            str(ref_geotiff),
            str(blank_path),
        ]
        subprocess.run(create_cmd, check=True, env=env)
        _shutil.copy2(str(blank_path), str(out_path))

        rasterize_cmd = [
            gdal_rasterize,
            "-burn", "1.0",
            "-ot", "Float32",
            "-a_srs", "EPSG:4326",
            str(filtered_path),
            str(out_path),
        ]
        subprocess.run(rasterize_cmd, check=True, env=env)


def _rasterize_forest_numpy(
    forest_features: list,
    out_path: Path,
    w: int, h: int,
    origin_x: float, origin_y: float, pixel_x: float, pixel_y: float,
) -> None:
    """Pure numpy fallback rasterizer for forest polygons (WGS84 → UTM via pyproj).

    Requires numpy. Uses pyproj for coordinate conversion if available; without it
    assumes coordinates are already in the raster CRS (unusual but keeps it importable).
    Writes a minimal GeoTIFF via struct packing (no GDAL Python bindings required).
    """
    import numpy as np
    import struct

    mask = np.zeros((h, w), dtype=np.float32)

    # Try to set up WGS84 → UTM32N transformer.
    to_utm: Optional[object] = None
    try:
        from pyproj import Transformer
        to_utm = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    except ImportError:
        pass

    def _wgs84_to_utm(lon: float, lat: float) -> tuple[float, float]:
        if to_utm is not None:
            return to_utm.transform(lon, lat)
        return lon, lat  # assume already metric if no pyproj

    def _utm_to_pixel(x: float, y: float) -> tuple[int, int]:
        col = int((x - origin_x) / pixel_x)
        row = int((origin_y - y) / pixel_y)
        return col, row

    def _fill_polygon(coords_wgs: list) -> None:
        """Scan-fill a polygon into the mask array."""
        utm_pts = [_wgs84_to_utm(lon, lat) for lon, lat in coords_wgs]
        pix_pts = [_utm_to_pixel(x, y) for x, y in utm_pts]
        xs = [p[0] for p in pix_pts]; ys = [p[1] for p in pix_pts]
        if not xs:
            return
        r_min = max(0, min(ys)); r_max = min(h - 1, max(ys))
        c_min = max(0, min(xs)); c_max = min(w - 1, max(xs))
        n_pts = len(pix_pts)
        for row in range(r_min, r_max + 1):
            crossings: list[float] = []
            for i in range(n_pts):
                j = (i + 1) % n_pts
                y0, y1 = pix_pts[i][1], pix_pts[j][1]
                x0, x1 = pix_pts[i][0], pix_pts[j][0]
                if (y0 <= row < y1) or (y1 <= row < y0):
                    t = (row - y0) / (y1 - y0)
                    crossings.append(x0 + t * (x1 - x0))
            crossings.sort()
            for k in range(0, len(crossings) - 1, 2):
                c0 = max(0, int(crossings[k]))
                c1 = min(w, int(crossings[k + 1]) + 1)
                mask[row, c0:c1] = 1.0

    for feature in forest_features:
        geom = feature.get("geometry") or {}
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if gtype == "Polygon" and coords:
            _fill_polygon(coords[0])
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    _fill_polygon(poly[0])

    # Write a minimal uncompressed Float32 GeoTIFF via the tifffile or struct approach.
    # Use gdal_translate to write the GeoTIFF with correct georef if available.
    # Otherwise write a raw float32 array wrapped in a minimal TIFF structure.
    _write_float32_geotiff(out_path, mask, origin_x, origin_y, pixel_x, pixel_y)


def _write_float32_geotiff(
    out_path: Path,
    data: "numpy.ndarray",
    origin_x: float, origin_y: float,
    pixel_x: float, pixel_y: float,
) -> None:
    """Write a Float32 GeoTIFF with minimal TIFF metadata via gdal_translate.

    Writes data as a raw binary, then wraps it with gdal_translate to add
    geo-referencing. Falls back to writing a headerless .bin + .hdr if GDAL fails.
    """
    import numpy as np

    h, w = data.shape
    env = _vendored_gdal_env()
    translate_bin = _resolve_gdal_bin("gdal_translate")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        raw_path = tmp / "mask_raw.bin"
        raw_path.write_bytes(data.astype(np.float32).tobytes())

        # Write a minimal ENVI .hdr so gdal_translate can read the binary.
        hdr_path = tmp / "mask_raw.hdr"
        hdr_path.write_text(
            "ENVI\n"
            f"samples = {w}\n"
            f"lines   = {h}\n"
            "bands   = 1\n"
            "data type = 4\n"  # 4 = Float32 in ENVI
            "interleave = bsq\n"
            "byte order = 0\n",
            encoding="ascii",
        )

        cmd = [
            translate_bin,
            "-of", "GTiff",
            "-ot", "Float32",
            "-co", "COMPRESS=LZW",
            "-a_srs", "EPSG:25832",
            "-a_ullr",
            str(origin_x), str(origin_y),
            str(origin_x + w * pixel_x), str(origin_y - h * pixel_y),
            str(raw_path),
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, env=env)
        except subprocess.CalledProcessError:
            # Absolute last resort: just write the raw float32 array with a .tif extension.
            out_path.write_bytes(data.astype(np.float32).tobytes())
            print(f"[geo_import] warning: wrote raw float32 without TIFF header to {out_path}")


def greenness_mask(
    dop_geotiff: str,
    out_path: str,
    threshold: float = 0.08,
    gdal_calc_bin: Optional[str] = None,
) -> str:
    """Compute an RGB-greenness (ExG) mask from a DOP orthophoto.

    ExG = (2*G - R - B), normalised to [0, 1], then thresholded so that
    values below `threshold` are clamped to 0.  Produces a Float32 GeoTIFF
    with values ≈0 (non-vegetated) to 1 (strongly vegetated).

    Useful when no OSM land-use layer is available.  Requires the DOP to
    have at least 3 bands (R, G, B).

    Args:
        dop_geotiff: Path to an RGB DOP GeoTIFF (bands: 1=R, 2=G, 3=B).
        out_path: Output Float32 GeoTIFF path.
        threshold: ExG values below this are zeroed (removes pavement/water noise).
        gdal_calc_bin: Override path to gdal_calc.py; defaults to vendored/PATH.

    Returns:
        out_path on success.

    Raises:
        subprocess.CalledProcessError: If gdal_calc.py fails.
    """
    out_path_obj = Path(out_path)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)

    calc_bin = gdal_calc_bin or _resolve_gdal_bin("gdal_calc.py")
    env = _vendored_gdal_env()

    # ExG = 2G - R - B, normalised from [-2,2] range to [0,1]:
    # norm = (2G - R - B + 2) / 4  (shift + scale)
    # then threshold: max(0, norm - threshold/4_scaled)
    # Simpler: compute ExG01 = clip((2G-R-B+2)/4, 0, 1), then zero where < threshold.
    calc_expr = (
        f"(numpy.clip((2.0*B.astype(float)-A.astype(float)-C.astype(float)+2.0)/4.0,0,1)"
        f" * (((2.0*B.astype(float)-A.astype(float)-C.astype(float)+2.0)/4.0) > {threshold}))"
    )
    cmd = [
        calc_bin,
        "-A", str(dop_geotiff), "--A_band=1",
        "-B", str(dop_geotiff), "--B_band=2",
        "-C", str(dop_geotiff), "--C_band=3",
        "--outfile", str(out_path_obj),
        "--calc", calc_expr,
        "--type=Float32",
        "--co=COMPRESS=LZW",
        "--quiet",
        "--overwrite",
    ]
    subprocess.run(cmd, check=True, env=env)
    print(f"[geo_import] greenness_mask: ExG mask -> {out_path_obj.name}")
    return str(out_path_obj)


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
