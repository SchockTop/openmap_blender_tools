"""Tests for blender_tools.step_retessellate.

Pure-Python helpers tested directly. OCCT-dependent paths mocked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blender_tools.step_retessellate import (
    tessellation_params_for_quality,
    orientation_flip_indices,
    validate_input_path,
    retessellate_step_to_gltf,
    _QUALITY_PRESETS,
)


# ---------------------------------------------------------------------------
# TestTessellationParamsForQuality
# ---------------------------------------------------------------------------

class TestTessellationParamsForQuality:
    def test_hero_returns_correct_keys(self):
        result = tessellation_params_for_quality("hero")
        assert set(result.keys()) == {"linear_mm", "angular_rad", "description"}

    def test_mid_returns_correct_keys(self):
        result = tessellation_params_for_quality("mid")
        assert set(result.keys()) == {"linear_mm", "angular_rad", "description"}

    def test_wide_returns_correct_keys(self):
        result = tessellation_params_for_quality("wide")
        assert set(result.keys()) == {"linear_mm", "angular_rad", "description"}

    def test_background_returns_correct_keys(self):
        result = tessellation_params_for_quality("background")
        assert set(result.keys()) == {"linear_mm", "angular_rad", "description"}

    def test_hero_values(self):
        result = tessellation_params_for_quality("hero")
        assert result["linear_mm"] == pytest.approx(0.02)
        assert result["angular_rad"] == pytest.approx(0.1)

    def test_background_values(self):
        result = tessellation_params_for_quality("background")
        assert result["linear_mm"] == pytest.approx(1.00)
        assert result["angular_rad"] == pytest.approx(0.5)

    def test_unknown_preset_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown quality"):
            tessellation_params_for_quality("ultra")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            tessellation_params_for_quality("")

    def test_returned_dict_is_a_copy(self):
        """Mutating the returned dict must not affect the internal preset."""
        result = tessellation_params_for_quality("mid")
        original_linear = _QUALITY_PRESETS["mid"]["linear_mm"]
        result["linear_mm"] = 9999.0
        assert _QUALITY_PRESETS["mid"]["linear_mm"] == original_linear

    def test_two_calls_return_independent_dicts(self):
        r1 = tessellation_params_for_quality("wide")
        r2 = tessellation_params_for_quality("wide")
        r1["linear_mm"] = 9999.0
        assert r2["linear_mm"] != 9999.0


# ---------------------------------------------------------------------------
# TestOrientationFlipIndices
# ---------------------------------------------------------------------------

class TestOrientationFlipIndices:
    def test_not_reversed_identity(self):
        tris = [(0, 1, 2), (3, 4, 5)]
        assert orientation_flip_indices(tris, is_reversed=False) == tris

    def test_reversed_single_triangle(self):
        assert orientation_flip_indices([(0, 1, 2)], is_reversed=True) == [(0, 2, 1)]

    def test_reversed_empty(self):
        assert orientation_flip_indices([], is_reversed=True) == []

    def test_not_reversed_empty(self):
        assert orientation_flip_indices([], is_reversed=False) == []

    def test_reversed_multiple_triangles(self):
        tris = [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
        result = orientation_flip_indices(tris, is_reversed=True)
        assert result == [(0, 2, 1), (3, 5, 4), (6, 8, 7)]

    def test_not_reversed_returns_copy(self):
        """not-reversed path must return a new list, not the same object."""
        tris = [(0, 1, 2)]
        result = orientation_flip_indices(tris, is_reversed=False)
        assert result == tris
        assert result is not tris


# ---------------------------------------------------------------------------
# TestValidateInputPath
# ---------------------------------------------------------------------------

class TestValidateInputPath:
    def test_valid_step_exists(self, tmp_path):
        f = tmp_path / "model.step"
        f.write_text("STEP")
        result = validate_input_path(f)
        assert result == f.resolve()
        assert isinstance(result, Path)

    def test_valid_stp_exists(self, tmp_path):
        f = tmp_path / "model.stp"
        f.write_text("STP")
        result = validate_input_path(f)
        assert result == f.resolve()

    def test_valid_stpz_exists(self, tmp_path):
        f = tmp_path / "model.stpz"
        f.write_bytes(b"STPZ")
        result = validate_input_path(f)
        assert result == f.resolve()

    def test_catpart_rejected(self, tmp_path):
        f = tmp_path / "part.CATPart"
        f.write_bytes(b"CAT")
        with pytest.raises(ValueError, match="Datakit"):
            validate_input_path(f)

    def test_obj_rejected(self, tmp_path):
        f = tmp_path / "mesh.obj"
        f.write_text("obj")
        with pytest.raises(ValueError):
            validate_input_path(f)

    def test_nonexistent_raises_file_not_found(self, tmp_path):
        f = tmp_path / "ghost.step"
        with pytest.raises(FileNotFoundError):
            validate_input_path(f, allow_nonexistent=False)

    def test_nonexistent_with_allow_returns_path(self, tmp_path):
        f = tmp_path / "ghost.step"
        result = validate_input_path(f, allow_nonexistent=True)
        assert result == f.resolve()

    def test_returns_resolved_absolute_path(self, tmp_path):
        f = tmp_path / "model.step"
        f.write_text("STEP")
        result = validate_input_path(f)
        assert result.is_absolute()


# ---------------------------------------------------------------------------
# TestRetessellateStepToGltf
# ---------------------------------------------------------------------------

class TestRetessellateStepToGltf:
    def test_nonexistent_input_raises_file_not_found(self, tmp_path):
        step = tmp_path / "ghost.step"
        out = tmp_path / "out.gltf"
        with pytest.raises(FileNotFoundError):
            retessellate_step_to_gltf(step, out)

    def test_invalid_quality_raises_value_error(self, tmp_path):
        step = tmp_path / "model.step"
        step.write_text("STEP")
        out = tmp_path / "out.gltf"
        with pytest.raises(ValueError, match="Unknown quality"):
            retessellate_step_to_gltf(step, out, quality="ultra")

    def test_occt_not_installed_raises_runtime_error(self, tmp_path):
        """When _require_occt raises, we get RuntimeError with install hint."""
        step = tmp_path / "model.step"
        step.write_text("STEP")
        out = tmp_path / "out.gltf"

        with patch(
            "blender_tools.step_retessellate._require_occt",
            side_effect=RuntimeError("pythonocc-core not installed — pip install -e '.[cad]'"),
        ):
            with pytest.raises(RuntimeError, match="pythonocc"):
                retessellate_step_to_gltf(step, out)
