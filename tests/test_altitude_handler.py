"""Unit tests for altitude_handler — render_pre weight computation."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if "altitude_handler" in sys.modules:
        del sys.modules["altitude_handler"]
    import altitude_handler
    return altitude_handler


def test_weight_curve_at_low_altitude():
    h = _import_module()
    assert abs(h.compute_weight(50.0) - 0.6) < 1e-6
    assert abs(h.compute_weight(100.0) - 0.6) < 1e-6


def test_weight_curve_at_high_altitude():
    h = _import_module()
    assert abs(h.compute_weight(2000.0) - 0.15) < 1e-6
    # Just below 1000 m: weight is just above 0.15.
    near_high = h.compute_weight(999.0)
    assert 0.15 < near_high < 0.16


def test_weight_curve_midrange_is_monotonic():
    h = _import_module()
    a = h.compute_weight(200.0)
    b = h.compute_weight(500.0)
    c = h.compute_weight(800.0)
    assert a > b > c


def test_handler_writes_to_node_input():
    h = _import_module()
    fake_scene = MagicMock()
    fake_scene.camera.location.z = 500.0

    mat = MagicMock()
    mix_node = MagicMock()
    mix_node.inputs = {"Fac": MagicMock()}
    nodes = MagicMock()
    nodes.get.return_value = mix_node
    mat.node_tree.nodes = nodes

    fake_bpy = MagicMock()
    fake_bpy.data.materials.get.return_value = mat

    h.update_drape_weight(fake_scene, _bpy=fake_bpy)
    expected = h.compute_weight(500.0)
    assert mix_node.inputs["Fac"].default_value == expected


def test_handler_noop_when_no_camera():
    h = _import_module()
    fake_scene = MagicMock()
    fake_scene.camera = None
    fake_bpy = MagicMock()
    # Should not blow up.
    h.update_drape_weight(fake_scene, _bpy=fake_bpy)


def test_handler_noop_when_material_missing():
    h = _import_module()
    fake_scene = MagicMock()
    fake_scene.camera.location.z = 100.0
    fake_bpy = MagicMock()
    fake_bpy.data.materials.get.return_value = None
    # Should not blow up.
    h.update_drape_weight(fake_scene, _bpy=fake_bpy)
