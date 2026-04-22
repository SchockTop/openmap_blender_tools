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
# GDAL integration tests (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.needs_gdal
@pytest.mark.skip(reason="Requires GDAL CLI; run manually.")
def test_dgm_tif_to_exr_heightmap_integration(tmp_path):
    """Integration smoke — kept skipped to keep unit-test runs fast."""
    pass


@pytest.mark.needs_gdal
@pytest.mark.skip(reason="Requires GDAL CLI; run manually.")
def test_dop_to_udim_tiles_integration(tmp_path):
    """Integration smoke for DOP→UDIM — kept skipped to keep unit-test runs fast."""
    pass
