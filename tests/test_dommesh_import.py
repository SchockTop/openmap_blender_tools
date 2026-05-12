"""Unit tests for dommesh_import.py.

Pure-Python helpers tested without bpy. The bpy-dependent importer is covered by
smoke_dommesh.py (needs Blender).
"""
from __future__ import annotations

import json
from pathlib import Path

from blender_tools.dommesh_import import read_dommesh_meta, anchor_offset

FIX = Path(__file__).parent / "fixtures" / "dommesh_meta.json"


def test_read_dommesh_meta_returns_dict():
    meta = read_dommesh_meta(str(FIX))
    assert meta["losid"] == "125023_0"
    assert meta["anchor_epsg25832"] == [689977.0, 5506729.0]


def test_anchor_offset_with_scene_anchor():
    meta = read_dommesh_meta(str(FIX))
    # Scene anchored at (689900, 5506700); the cutout anchor is (689977, 5506729);
    # imported verts (which are cutout-anchor-relative) must move by
    # (cutout_anchor - scene_anchor) = (77, 29).
    dx, dy = anchor_offset(meta, scene_anchor=(689900.0, 5506700.0, 0.0))
    assert (dx, dy) == (77.0, 29.0)


def test_anchor_offset_without_scene_anchor_is_zero():
    meta = read_dommesh_meta(str(FIX))
    dx, dy = anchor_offset(meta, scene_anchor=None)
    assert (dx, dy) == (0.0, 0.0)
