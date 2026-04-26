"""Tests for buildings_textured feature module — bpy is mocked.

The feature module is bpy-free at import time (uses context['bpy']), so we
build a minimal fake-bpy that exercises the data-API surface used by apply().
"""
from __future__ import annotations
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _build_fake_bpy():
    """Construct a fake bpy module exposing the data/material/node API surface."""
    bpy = types.ModuleType("bpy_fake")

    # Materials registry: dict-like.
    class _MatDict(dict):
        def new(self, name):
            mat = MagicMock(name=f"Material({name})")
            mat.name = name
            mat.use_nodes = False
            mat.node_tree = MagicMock()
            mat.node_tree.nodes = MagicMock()
            mat.node_tree.nodes.clear = MagicMock()
            # nodes.new returns a MagicMock that has inputs/outputs subscriptable.
            def _new_node(_type):
                node = MagicMock()
                # Make inputs/outputs return MagicMock when subscripted.
                node.inputs = MagicMock()
                node.inputs.__getitem__ = lambda self, k: MagicMock(default_value=None)
                node.outputs = MagicMock()
                node.outputs.__getitem__ = lambda self, k: MagicMock()
                return node
            mat.node_tree.nodes.new = _new_node
            mat.node_tree.links = MagicMock()
            mat.node_tree.links.new = MagicMock()
            self[name] = mat
            return mat

    class _ImageDict(dict):
        def load(self, path, check_existing=False):
            img = MagicMock()
            img.tiles = MagicMock()
            img.tiles.new = MagicMock()
            img.source = ""
            self[path] = img
            return img

    bpy.data = MagicMock()
    bpy.data.materials = _MatDict()
    bpy.data.images = _ImageDict()
    return bpy


def _fake_building(name="CityJSON_001", n_faces=6):
    """Fake building object with a mesh of n_faces polygons."""
    obj = MagicMock()
    obj.type = "MESH"
    obj.name = name
    polys = []
    for i in range(n_faces):
        poly = MagicMock()
        # Mix of normals: top, side, bottom.
        if i == 0:
            poly.normal = MagicMock(z=1.0)   # roof
        elif i == n_faces - 1:
            poly.normal = MagicMock(z=-1.0)  # ground
        else:
            poly.normal = MagicMock(z=0.0)   # wall
        poly.material_index = -1
        polys.append(poly)
    obj.data = MagicMock()
    obj.data.polygons = polys
    obj.data.materials = MagicMock()
    obj.data.materials.clear = MagicMock()
    obj.data.materials.append = MagicMock()
    obj.data.calc_loop_triangles = MagicMock()
    return obj


def _import_feature():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    for k in list(sys.modules):
        if k in {"features", "features.buildings_textured"}:
            del sys.modules[k]
    import features.buildings_textured as bt  # type: ignore
    return bt


def test_apply_no_buildings_returns_empty():
    bt = _import_feature()
    bpy = _build_fake_bpy()
    ctx = {"bpy": bpy, "building_objs": [], "bbox_utm32n": (0, 0, 100, 100),
           "ortho_dir": None}
    out = bt.apply(ctx)
    assert out == {}


def test_apply_skips_non_cityjson_objects():
    bt = _import_feature()
    bpy = _build_fake_bpy()
    obj = _fake_building(name="NotABuilding")
    ctx = {"bpy": bpy, "building_objs": [obj], "bbox_utm32n": (0, 0, 100, 100),
           "ortho_dir": None}
    out = bt.apply(ctx)
    assert out["buildings_textured_count"] == 0


def test_apply_assigns_three_material_slots():
    bt = _import_feature()
    bpy = _build_fake_bpy()
    obj = _fake_building()
    ctx = {"bpy": bpy, "building_objs": [obj], "bbox_utm32n": (0, 0, 100, 100),
           "ortho_dir": None}
    out = bt.apply(ctx)
    assert out["buildings_textured_count"] == 1
    # 3 material slots appended (roof, wall, ground)
    assert obj.data.materials.append.call_count == 3
    obj.data.materials.clear.assert_called_once()


def test_apply_material_index_assignment_by_normal():
    bt = _import_feature()
    bpy = _build_fake_bpy()
    obj = _fake_building(n_faces=3)
    # face 0: nz=1 -> roof, face 1: nz=0 -> wall, face 2: nz=-1 -> ground/sloped
    ctx = {"bpy": bpy, "building_objs": [obj], "bbox_utm32n": (0, 0, 100, 100),
           "ortho_dir": None}
    bt.apply(ctx)
    polys = obj.data.polygons
    assert polys[0].material_index == 0  # roof (nz=1.0)
    assert polys[1].material_index == 1  # wall (nz=0.0)
    assert polys[2].material_index == 2  # ground (nz=-1.0, |nz|=1.0 not < 0.3, not > 0.7)


def test_apply_idempotent_reuses_existing_materials():
    bt = _import_feature()
    bpy = _build_fake_bpy()
    obj1 = _fake_building(name="CityJSON_A")
    obj2 = _fake_building(name="CityJSON_B")
    ctx = {"bpy": bpy, "building_objs": [obj1, obj2],
           "bbox_utm32n": (0, 0, 100, 100), "ortho_dir": None}
    bt.apply(ctx)
    # Only 3 unique materials in bpy.data.materials.
    assert set(bpy.data.materials.keys()) == {"BldRoof_DOP", "BldWall_PBR", "BldGround"}


def test_module_exposes_NAME_and_DESCRIPTION():
    bt = _import_feature()
    assert bt.NAME == "buildings-textured"
    assert isinstance(bt.DESCRIPTION, str) and len(bt.DESCRIPTION) > 0
