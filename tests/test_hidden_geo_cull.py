"""Tests for blender_tools.hidden_geo_cull.

Pure-Python helpers tested directly. bpy-dependent functions tested via
MagicMock injected via patch.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blender_tools.hidden_geo_cull import (
    compile_hidden_patterns,
    name_matches_any,
    sample_camera_positions_on_sphere,
    cull_by_name_pattern,
    cull_by_render_face_id_visibility,
    _DEFAULT_HIDDEN_PATTERNS,
)


# ---------------------------------------------------------------------------
# TestCompileHiddenPatterns
# ---------------------------------------------------------------------------

class TestCompileHiddenPatterns:
    def test_default_returns_at_least_nine(self):
        patterns = compile_hidden_patterns()
        assert len(patterns) >= 9

    def test_default_patterns_are_compiled(self):
        patterns = compile_hidden_patterns()
        for p in patterns:
            assert isinstance(p, re.Pattern)

    def test_custom_patterns_returns_same_count(self):
        custom = [r"\bfoo\b", r"\bbar\b", r"\bbaz\b"]
        patterns = compile_hidden_patterns(custom)
        assert len(patterns) == 3

    def test_empty_list_returns_empty(self):
        patterns = compile_hidden_patterns([])
        assert patterns == []

    def test_patterns_are_case_insensitive(self):
        patterns = compile_hidden_patterns([r"\bbolt\b"])
        assert patterns[0].search("BOLT") is not None


# ---------------------------------------------------------------------------
# TestNameMatchesAny
# ---------------------------------------------------------------------------

class TestNameMatchesAny:
    @pytest.fixture
    def default_compiled(self):
        return compile_hidden_patterns()

    def test_bolt_name_matches(self, default_compiled):
        # word-boundary \bbolt\b matches at non-word-char boundary
        assert name_matches_any("bolt", default_compiled) is True

    def test_bolt_hyphen_m6_matches(self, default_compiled):
        assert name_matches_any("bolt-m6", default_compiled) is True

    def test_bracket_does_not_match(self, default_compiled):
        assert name_matches_any("Bracket", default_compiled) is False

    def test_wire_hyphen_harness_matches(self, default_compiled):
        # underscore is a word-char, so "wire_harness" doesn't match \bwire\b
        # but "wire-harness" does
        assert name_matches_any("wire-harness", default_compiled) is True

    def test_wire_standalone_matches(self, default_compiled):
        assert name_matches_any("WIRE", default_compiled) is True

    def test_inner_hyphen_ring_matches_case_insensitive(self, default_compiled):
        # \binner\b matches at hyphen boundary
        assert name_matches_any("INNER-RING", default_compiled) is True

    def test_empty_patterns_list_never_matches(self):
        compiled = compile_hidden_patterns([])
        assert name_matches_any("bolt", compiled) is False

    def test_nut_standalone_matches(self, default_compiled):
        assert name_matches_any("NUT", default_compiled) is True

    def test_gasket_standalone_matches(self, default_compiled):
        assert name_matches_any("gasket", default_compiled) is True

    def test_cable_standalone_matches(self, default_compiled):
        assert name_matches_any("cable", default_compiled) is True


# ---------------------------------------------------------------------------
# TestSampleCameraPositionsOnSphere
# ---------------------------------------------------------------------------

class TestSampleCameraPositionsOnSphere:
    def _dist(self, p, center=(0.0, 0.0, 0.0)):
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(p, center)))

    def test_n1_returns_one_position(self):
        result = sample_camera_positions_on_sphere(1, 5.0)
        assert len(result) == 1

    def test_n1_distance_from_center_approx_radius(self):
        result = sample_camera_positions_on_sphere(1, 5.0)
        assert self._dist(result[0]) == pytest.approx(5.0, abs=1e-6)

    def test_n20_returns_twenty_positions(self):
        result = sample_camera_positions_on_sphere(20, 10.0)
        assert len(result) == 20

    def test_n20_all_at_radius(self):
        radius = 10.0
        result = sample_camera_positions_on_sphere(20, radius)
        for pos in result:
            assert self._dist(pos) == pytest.approx(radius, abs=1e-6)

    def test_n0_raises_value_error(self):
        with pytest.raises(ValueError, match="n must be"):
            sample_camera_positions_on_sphere(0, 5.0)

    def test_negative_n_raises_value_error(self):
        with pytest.raises(ValueError):
            sample_camera_positions_on_sphere(-1, 5.0)

    def test_zero_radius_raises_value_error(self):
        with pytest.raises(ValueError, match="radius must be positive"):
            sample_camera_positions_on_sphere(5, 0.0)

    def test_negative_radius_raises_value_error(self):
        with pytest.raises(ValueError):
            sample_camera_positions_on_sphere(5, -3.0)

    def test_custom_center_offsets_positions(self):
        center = (100.0, 200.0, 300.0)
        radius = 5.0
        result = sample_camera_positions_on_sphere(10, radius, center=center)
        for pos in result:
            assert self._dist(pos, center) == pytest.approx(radius, abs=1e-6)


# ---------------------------------------------------------------------------
# TestCullByNamePattern — mocked bpy
# ---------------------------------------------------------------------------

def _make_mock_bpy(objects):
    """Build a bpy MagicMock with a list of mock objects.

    Each item in 'objects' is a dict with keys: name, type.
    """
    mock_bpy = MagicMock()

    mock_objs = []
    for spec in objects:
        obj = MagicMock()
        obj.name = spec["name"]
        obj.type = spec.get("type", "MESH")
        # users_collection: one dummy collection per object.
        dummy_col = MagicMock()
        obj.users_collection = [dummy_col]
        obj.hide_viewport = False
        obj.hide_render = False
        mock_objs.append(obj)

    mock_bpy.data.objects.__iter__ = MagicMock(return_value=iter(mock_objs))

    # Hidden collection not yet existing → get returns None → new returns mock.
    mock_bpy.data.collections.get.return_value = None
    hidden_col = MagicMock()
    mock_bpy.data.collections.new.return_value = hidden_col

    return mock_bpy, mock_objs, hidden_col


class TestCullByNamePattern:
    def test_no_matching_objects_returns_zero(self):
        mock_bpy, _, _ = _make_mock_bpy([
            {"name": "Bracket-A", "type": "MESH"},
            {"name": "Fuselage", "type": "MESH"},
        ])
        with patch("blender_tools.hidden_geo_cull._require_bpy", return_value=mock_bpy):
            count = cull_by_name_pattern()
        assert count == 0

    def test_bolt_and_wire_matched_bracket_not(self):
        # Use names that match \bbolt\b and \bwire\b at non-word-char boundaries.
        mock_bpy, mock_objs, hidden_col = _make_mock_bpy([
            {"name": "bolt-m6", "type": "MESH"},
            {"name": "Bracket-01", "type": "MESH"},
            {"name": "wire-harness", "type": "MESH"},
        ])
        with patch("blender_tools.hidden_geo_cull._require_bpy", return_value=mock_bpy):
            count = cull_by_name_pattern()
        assert count == 2

    def test_matched_objects_have_hide_render_true(self):
        # "NUT" (standalone) matches \bnut\b.
        mock_bpy, mock_objs, hidden_col = _make_mock_bpy([
            {"name": "NUT", "type": "MESH"},
            {"name": "Panel", "type": "MESH"},
        ])
        with patch("blender_tools.hidden_geo_cull._require_bpy", return_value=mock_bpy):
            cull_by_name_pattern()
        # NUT is mock_objs[0]
        assert mock_objs[0].hide_render is True
        assert mock_objs[0].hide_viewport is True

    def test_non_mesh_objects_ignored_even_if_name_matches(self):
        mock_bpy, mock_objs, hidden_col = _make_mock_bpy([
            {"name": "bolt", "type": "LIGHT"},
            {"name": "bolt", "type": "CAMERA"},
        ])
        with patch("blender_tools.hidden_geo_cull._require_bpy", return_value=mock_bpy):
            count = cull_by_name_pattern()
        assert count == 0

    def test_bpy_not_available_raises_runtime_error(self):
        with patch(
            "blender_tools.hidden_geo_cull._require_bpy",
            side_effect=RuntimeError("hidden_geo_cull requires Blender's bundled Python (bpy)."),
        ):
            with pytest.raises(RuntimeError, match="bpy"):
                cull_by_name_pattern()


# ---------------------------------------------------------------------------
# TestCullByRenderFaceIdVisibility — mocked bpy
# ---------------------------------------------------------------------------

class TestCullByRenderFaceIdVisibility:
    def test_returns_zero_scaffold(self):
        mock_bpy = MagicMock()
        with patch("blender_tools.hidden_geo_cull._require_bpy", return_value=mock_bpy):
            result = cull_by_render_face_id_visibility()
        assert result == 0

    def test_no_exceptions_on_valid_call(self):
        mock_bpy = MagicMock()
        with patch("blender_tools.hidden_geo_cull._require_bpy", return_value=mock_bpy):
            result = cull_by_render_face_id_visibility(n_sample_cameras=10, radius_meters=5.0)
        assert isinstance(result, int)

    def test_require_bpy_import_error_raises_runtime_error(self):
        with patch(
            "blender_tools.hidden_geo_cull._require_bpy",
            side_effect=RuntimeError("hidden_geo_cull requires Blender's bundled Python (bpy)."),
        ):
            with pytest.raises(RuntimeError, match="bpy"):
                cull_by_render_face_id_visibility()
