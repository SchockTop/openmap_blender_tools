"""Tests for blender_tools.cleanup_pymeshlab.

Pure-Python helpers tested directly. pymeshlab-dependent paths mocked via
sys.modules injection.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from blender_tools.cleanup_pymeshlab import (
    default_filter_chain,
    validate_filter_chain,
    clean_cad_mesh,
    _DEFAULT_FILTER_CHAIN,
    _VALID_T_VERTEX_METHODS,
)


# ---------------------------------------------------------------------------
# TestDefaultFilterChain
# ---------------------------------------------------------------------------

class TestDefaultFilterChain:
    def test_returns_list(self):
        chain = default_filter_chain()
        assert isinstance(chain, list)

    def test_at_least_seven_entries(self):
        chain = default_filter_chain()
        assert len(chain) >= 7

    def test_first_entry_is_remove_duplicate_vertices(self):
        chain = default_filter_chain()
        assert chain[0][0] == "meshing_remove_duplicate_vertices"

    def test_last_entry_is_reorient_faces(self):
        chain = default_filter_chain()
        assert chain[-1][0] == "meshing_re_orient_faces_coherently"

    def test_returned_value_is_deep_copy(self):
        """Mutating a nested dict in the returned chain must not affect the constant."""
        chain = default_filter_chain()
        # Find the T-vertex entry and mutate its params.
        for name, params in chain:
            if name == "meshing_remove_t_vertices":
                params["method"] = "MUTATED"
                break
        # The internal constant must be untouched.
        for name, params in _DEFAULT_FILTER_CHAIN:
            if name == "meshing_remove_t_vertices":
                assert params.get("method") != "MUTATED"
                break

    def test_two_calls_return_independent_lists(self):
        c1 = default_filter_chain()
        c2 = default_filter_chain()
        c1.append(("meshing_extra", {}))
        assert len(c2) < len(c1)


# ---------------------------------------------------------------------------
# TestValidateFilterChain
# ---------------------------------------------------------------------------

class TestValidateFilterChain:
    def test_valid_default_chain_no_error(self):
        validate_filter_chain(default_filter_chain())  # must not raise

    def test_non_list_raises_value_error(self):
        with pytest.raises(ValueError, match="list"):
            validate_filter_chain(("meshing_remove_duplicate_vertices", {}))  # type: ignore[arg-type]

    def test_entry_not_a_tuple_raises_value_error(self):
        bad = [["meshing_remove_duplicate_vertices", {}]]
        with pytest.raises(ValueError, match="tuple"):
            validate_filter_chain(bad)  # type: ignore[arg-type]

    def test_entry_tuple_wrong_length_raises_value_error(self):
        bad = [("meshing_remove_duplicate_vertices",)]
        with pytest.raises(ValueError, match="tuple"):
            validate_filter_chain(bad)  # type: ignore[arg-type]

    def test_filter_name_not_meshing_prefix_raises(self):
        bad = [("clean_vertices", {})]
        with pytest.raises(ValueError, match="meshing_"):
            validate_filter_chain(bad)

    def test_params_not_dict_raises(self):
        bad = [("meshing_remove_duplicate_vertices", [])]
        with pytest.raises(ValueError, match="dict"):
            validate_filter_chain(bad)  # type: ignore[arg-type]

    def test_duplicate_filter_name_raises(self):
        bad = [
            ("meshing_remove_duplicate_vertices", {}),
            ("meshing_remove_duplicate_vertices", {}),
        ]
        with pytest.raises(ValueError, match="appears twice"):
            validate_filter_chain(bad)

    def test_invalid_t_vertex_method_raises(self):
        bad = [("meshing_remove_t_vertices", {"method": "Bad Method"})]
        with pytest.raises(ValueError, match="invalid"):
            validate_filter_chain(bad)

    def test_valid_t_vertex_edge_collapse_no_error(self):
        chain = [("meshing_remove_t_vertices", {"method": "Edge Collapse"})]
        validate_filter_chain(chain)  # must not raise

    def test_valid_t_vertex_edge_flip_no_error(self):
        chain = [("meshing_remove_t_vertices", {"method": "Edge Flip"})]
        validate_filter_chain(chain)  # must not raise

    def test_t_vertex_no_method_key_no_error(self):
        """If 'method' key is absent entirely, validation must pass."""
        chain = [("meshing_remove_t_vertices", {"threshold": 40})]
        validate_filter_chain(chain)  # must not raise


# ---------------------------------------------------------------------------
# TestCleanCadMesh
# ---------------------------------------------------------------------------

class TestCleanCadMesh:
    def _make_mock_pymeshlab(self):
        """Build a MagicMock that simulates the pymeshlab module."""
        mock_pml = MagicMock()
        mock_ms = MagicMock()
        mock_pml.MeshSet.return_value = mock_ms
        return mock_pml, mock_ms

    def test_calls_load_apply_save_in_order(self, tmp_path):
        input_mesh = tmp_path / "in.obj"
        input_mesh.write_text("obj")
        output_mesh = tmp_path / "out.obj"

        mock_pml, mock_ms = self._make_mock_pymeshlab()
        with patch("blender_tools.cleanup_pymeshlab._require_pymeshlab", return_value=mock_pml):
            result = clean_cad_mesh(input_mesh, output_mesh)

        mock_pml.MeshSet.assert_called_once()
        mock_ms.load_new_mesh.assert_called_once_with(str(input_mesh))
        mock_ms.save_current_mesh.assert_called_once_with(str(output_mesh))
        assert result == output_mesh

    def test_apply_filter_called_once_per_chain_entry(self, tmp_path):
        input_mesh = tmp_path / "in.obj"
        input_mesh.write_text("obj")
        output_mesh = tmp_path / "out.obj"

        chain = default_filter_chain()
        mock_pml, mock_ms = self._make_mock_pymeshlab()
        with patch("blender_tools.cleanup_pymeshlab._require_pymeshlab", return_value=mock_pml):
            clean_cad_mesh(input_mesh, output_mesh, filter_chain=chain)

        assert mock_ms.apply_filter.call_count == len(chain)

    def test_custom_chain_used(self, tmp_path):
        input_mesh = tmp_path / "in.obj"
        input_mesh.write_text("obj")
        output_mesh = tmp_path / "out.obj"

        custom_chain = [("meshing_remove_null_faces", {})]
        mock_pml, mock_ms = self._make_mock_pymeshlab()
        with patch("blender_tools.cleanup_pymeshlab._require_pymeshlab", return_value=mock_pml):
            clean_cad_mesh(input_mesh, output_mesh, filter_chain=custom_chain)

        mock_ms.apply_filter.assert_called_once_with("meshing_remove_null_faces")
