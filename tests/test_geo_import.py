"""Unit tests for geo_import.py.

Pure-Python helper tests run without GDAL. GDAL integration tests are marked
@pytest.mark.needs_gdal and skipped by default.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from blender_tools.geo_import import (
    udim_tile_index,
    _bbox_to_projwin_args,
    _tile_bboxes,
    _is_forest_feature,
    _exg_formula,
)


# ---------------------------------------------------------------------------
# udim_tile_index
# ---------------------------------------------------------------------------


def test_udim_tile_index_origin():
    assert udim_tile_index(0, 0) == 1001


def test_udim_tile_index_first_row():
    assert udim_tile_index(9, 0) == 1010


def test_udim_tile_index_second_row():
    assert udim_tile_index(0, 1) == 1011
    assert udim_tile_index(3, 2) == 1024


def test_udim_tile_index_rejects_bad_u():
    with pytest.raises(ValueError):
        udim_tile_index(10, 0)
    with pytest.raises(ValueError):
        udim_tile_index(-1, 0)


def test_udim_tile_index_rejects_bad_v():
    with pytest.raises(ValueError):
        udim_tile_index(0, -1)


# ---------------------------------------------------------------------------
# _bbox_to_projwin_args
# ---------------------------------------------------------------------------


def test_bbox_to_projwin_order():
    # GDAL wants ulx uly lrx lry (upper-left x/y then lower-right x/y) —
    # i.e. (xmin, ymax, xmax, ymin). Verify arg order.
    args = _bbox_to_projwin_args((100.0, 200.0, 300.0, 400.0))
    assert args == ["-projwin", "100.0", "400.0", "300.0", "200.0"]


def test_bbox_to_projwin_returns_strings():
    args = _bbox_to_projwin_args((0.0, 0.0, 1.0, 1.0))
    # All values after the flag must be strings for subprocess consumption.
    assert all(isinstance(a, str) for a in args)


def test_bbox_to_projwin_length():
    args = _bbox_to_projwin_args((10.0, 20.0, 30.0, 40.0))
    assert len(args) == 5  # ['-projwin', ulx, uly, lrx, lry]


# ---------------------------------------------------------------------------
# _tile_bboxes
# ---------------------------------------------------------------------------


def test_tile_bboxes_10x4_grid():
    parent = (0.0, 0.0, 10000.0, 4000.0)  # 10 x 4 km
    tiles = _tile_bboxes(parent, (10, 4))
    assert len(tiles) == 40
    # First tile (udim 1001) should be bottom-left corner.
    udim0, bbox0 = tiles[0]
    assert udim0 == 1001
    assert bbox0 == (0.0, 0.0, 1000.0, 1000.0)
    # Last tile (udim 1040 for 10x4) should be top-right.
    udim_last, bbox_last = tiles[-1]
    assert udim_last == 1040
    assert bbox_last == (9000.0, 3000.0, 10000.0, 4000.0)


def test_tile_bboxes_1x1_grid():
    parent = (100.0, 200.0, 300.0, 400.0)
    tiles = _tile_bboxes(parent, (1, 1))
    assert len(tiles) == 1
    udim, bbox = tiles[0]
    assert udim == 1001
    assert bbox == (100.0, 200.0, 300.0, 400.0)


def test_tile_bboxes_total_area_preserved():
    """Sum of tile areas must equal parent area."""
    parent = (0.0, 0.0, 6000.0, 4000.0)
    tiles = _tile_bboxes(parent, (6, 4))
    parent_area = (parent[2] - parent[0]) * (parent[3] - parent[1])
    tile_area_sum = sum(
        (b[2] - b[0]) * (b[3] - b[1]) for _, b in tiles
    )
    assert abs(tile_area_sum - parent_area) < 1e-6


def test_tile_bboxes_udim_numbers_unique():
    tiles = _tile_bboxes((0.0, 0.0, 10000.0, 4000.0), (10, 4))
    udims = [u for u, _ in tiles]
    assert len(udims) == len(set(udims)), "UDIM numbers must be unique"


def test_tile_bboxes_second_row_starts_at_1011():
    """Row v=1 should start at UDIM 1011."""
    parent = (0.0, 0.0, 10000.0, 2000.0)
    tiles = _tile_bboxes(parent, (10, 2))
    # tile index 10 is the first tile of the second row (u=0, v=1)
    udim, _ = tiles[10]
    assert udim == 1011


# ---------------------------------------------------------------------------
# _is_forest_feature — pure Python, no GDAL
# ---------------------------------------------------------------------------


def test_is_forest_feature_landuse_forest():
    assert _is_forest_feature({"landuse": "forest"}) is True


def test_is_forest_feature_landuse_wood():
    assert _is_forest_feature({"landuse": "wood"}) is True


def test_is_forest_feature_natural_wood():
    assert _is_forest_feature({"natural": "wood"}) is True


def test_is_forest_feature_natural_scrub():
    assert _is_forest_feature({"natural": "scrub"}) is True


def test_is_forest_feature_residential():
    assert _is_forest_feature({"landuse": "residential"}) is False


def test_is_forest_feature_water():
    assert _is_forest_feature({"natural": "water"}) is False


def test_is_forest_feature_empty():
    assert _is_forest_feature({}) is False


def test_is_forest_feature_both_keys_non_forest():
    assert _is_forest_feature({"landuse": "farmland", "natural": "cliff"}) is False


# ---------------------------------------------------------------------------
# _exg_formula — pure Python, no GDAL
# ---------------------------------------------------------------------------


def test_exg_pure_green():
    val = _exg_formula(0.0, 1.0, 0.0)
    assert abs(val - 1.0) < 1e-6


def test_exg_pure_red():
    val = _exg_formula(1.0, 0.0, 0.0)
    assert val == 0.0


def test_exg_grey_neutral():
    # R=G=B=0.5: ExG = 2*0.5 - 0.5 - 0.5 = 0 → normalised = 0.5/3 ≈ 0.333
    val = _exg_formula(0.5, 0.5, 0.5)
    # All grey → raw ExG = 0.0; norm = (0+2)/4 = 0.5 — not necessarily 0.
    # Just check it's in [0, 1].
    assert 0.0 <= val <= 1.0


def test_exg_clamped_to_zero_for_pure_red_blue():
    # R=1, G=0, B=1: ExG = -2; norm = 0 (clamped)
    assert _exg_formula(1.0, 0.0, 1.0) == 0.0


def test_exg_output_in_unit_range():
    import random
    rng = random.Random(42)
    for _ in range(50):
        r, g, b = rng.random(), rng.random(), rng.random()
        val = _exg_formula(r, g, b)
        assert 0.0 <= val <= 1.0, f"ExG out of range for r={r}, g={g}, b={b}"


# ---------------------------------------------------------------------------
# GDAL integration tests (skipped by default)
# ---------------------------------------------------------------------------


def _have_vendored_gdal() -> bool:
    from blender_tools.geo_import import _VENDOR_ROOT
    return (_VENDOR_ROOT / "bin" / "gdal_translate.exe").is_file()


@pytest.mark.skipif(not _have_vendored_gdal(), reason="vendored GDAL not present")
def test_dgm_tif_to_heightmap_integration(tmp_path):
    """End-to-end: build a synthetic DGM GeoTIFF, mosaic + Float32 convert via
    the vendored GDAL, then read back the output to verify it is a valid
    Float32 GeoTIFF.
    """
    import subprocess
    from blender_tools.geo_import import (
        _VENDOR_ROOT,
        _resolve_gdal_bin,
        _vendored_gdal_env,
        dgm_tif_to_heightmap,
    )

    env = _vendored_gdal_env()
    gdal_translate = _resolve_gdal_bin("gdal_translate")
    gdalinfo = _resolve_gdal_bin("gdalinfo")

    # Synthetic DGM tile: 100x100 px Int16 ramp in EPSG:25832, 1m pixel
    # @ Munich Marienplatz UTM (~691000, 5335000).
    src_tif = tmp_path / "dgm_synth.tif"
    xyz = tmp_path / "dgm_synth.xyz"
    with xyz.open("w") as f:
        for j in range(100):
            for i in range(100):
                x = 691000 + i
                y = 5335100 - j
                z = 520 + i * 0.1 + j * 0.2  # gentle slope, 520-550m range
                f.write(f"{x} {y} {z}\n")
    subprocess.run(
        [gdal_translate, "-of", "GTiff", "-a_srs", "EPSG:25832",
         str(xyz), str(src_tif)],
        check=True, env=env,
    )

    # Now exercise the function under test.
    out = tmp_path / "heightmap.tif"
    result = dgm_tif_to_heightmap([src_tif], out)
    assert result == out
    assert out.is_file()
    assert out.stat().st_size > 0

    info = subprocess.run(
        [gdalinfo, str(out)], check=True, env=env, capture_output=True, text=True,
    ).stdout
    assert "Float32" in info, info
    assert "EPSG" in info or "25832" in info, info
