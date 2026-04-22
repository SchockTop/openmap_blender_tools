"""Unit tests for ndvi_scatter.py.

Pure-Python helpers run without any external deps. gdal_calc.py invocation
is tested via mocked subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from blender_tools.ndvi_scatter import (
    _gdal_calc_cmd,
    compute_ndvi,
    ndvi_to_density_config,
    ndvi_to_density_value,
)


# ---------------------------------------------------------------------------
# _gdal_calc_cmd
# ---------------------------------------------------------------------------


def test_gdal_calc_cmd_has_red_band(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    cmd = _gdal_calc_cmd(red, nir, out)
    assert "-A" in cmd
    a_idx = cmd.index("-A")
    assert cmd[a_idx + 1] == str(red)


def test_gdal_calc_cmd_has_nir_band(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    cmd = _gdal_calc_cmd(red, nir, out)
    assert "-B" in cmd
    b_idx = cmd.index("-B")
    assert cmd[b_idx + 1] == str(nir)


def test_gdal_calc_cmd_has_outfile(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    cmd = _gdal_calc_cmd(red, nir, out)
    assert "--outfile" in cmd
    out_idx = cmd.index("--outfile")
    assert cmd[out_idx + 1] == str(out)


def test_gdal_calc_cmd_calc_string_contains_ndvi_formula(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    cmd = _gdal_calc_cmd(red, nir, out)
    calc_args = [a for a in cmd if "astype" in a]
    assert len(calc_args) == 1
    assert "B.astype(float) - A.astype(float)" in calc_args[0]


def test_gdal_calc_cmd_float32_output(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    cmd = _gdal_calc_cmd(red, nir, out)
    assert "--type=Float32" in cmd


def test_gdal_calc_cmd_custom_binary(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    cmd = _gdal_calc_cmd(red, nir, out, gdal_calc_bin="/usr/bin/gdal_calc.py")
    assert cmd[0] == "/usr/bin/gdal_calc.py"


# ---------------------------------------------------------------------------
# ndvi_to_density_value
# ---------------------------------------------------------------------------


def test_density_value_below_threshold_low():
    """NDVI at or below threshold_low → 0.0."""
    assert ndvi_to_density_value(0.1) == pytest.approx(0.0)
    assert ndvi_to_density_value(0.2) == pytest.approx(0.0)


def test_density_value_above_threshold_high():
    """NDVI at or above threshold_high → max_density_per_m2."""
    assert ndvi_to_density_value(0.8) == pytest.approx(0.5)
    assert ndvi_to_density_value(0.9) == pytest.approx(0.5)


def test_density_value_midpoint():
    """NDVI at midpoint of [0.2, 0.8] → half of max_density_per_m2."""
    mid = (0.2 + 0.8) / 2  # 0.5
    assert ndvi_to_density_value(mid) == pytest.approx(0.25)


def test_density_value_custom_thresholds():
    """Custom thresholds + max density produce expected linear interpolation."""
    result = ndvi_to_density_value(
        0.5, threshold_low=0.0, threshold_high=1.0, max_density_per_m2=1.0
    )
    assert result == pytest.approx(0.5)


def test_density_value_negative_ndvi():
    """Negative NDVI (below threshold_low=0.2) → 0.0."""
    assert ndvi_to_density_value(-0.5) == pytest.approx(0.0)


def test_density_value_quarter_point():
    """NDVI at 25 % of range → 25 % of max density."""
    low, high = 0.2, 0.8
    ndvi = low + 0.25 * (high - low)  # 0.35
    result = ndvi_to_density_value(ndvi, threshold_low=low, threshold_high=high)
    assert result == pytest.approx(0.25 * 0.5)


# ---------------------------------------------------------------------------
# ndvi_to_density_config
# ---------------------------------------------------------------------------


def test_density_config_returns_required_keys(tmp_path):
    """Default config contains all required GN keys."""
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif)
    for key in (
        "ndvi_image_path",
        "uv_map_name",
        "color_ramp_stops",
        "density_multiplier",
        "distribution_method",
        "colorspace",
        "interpolation",
    ):
        assert key in cfg, f"Missing key: {key}"


def test_density_config_color_ramp_has_two_stops(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif)
    assert len(cfg["color_ramp_stops"]) == 2


def test_density_config_colorspace_non_color(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif)
    assert cfg["colorspace"] == "Non-Color"


def test_density_config_interpolation_linear(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif)
    assert cfg["interpolation"] == "Linear"


def test_density_config_distribution_method_default(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif)
    assert cfg["distribution_method"] == "POISSON"


def test_density_config_random_method_accepted(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif, distribution_method="RANDOM")
    assert cfg["distribution_method"] == "RANDOM"


def test_density_config_rejects_invalid_distribution(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    with pytest.raises(ValueError, match="distribution_method must be POISSON or RANDOM"):
        ndvi_to_density_config(ndvi_tif, distribution_method="HALTON")


def test_density_config_rejects_low_ge_high(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    with pytest.raises(ValueError, match="thresholds must satisfy"):
        ndvi_to_density_config(ndvi_tif, threshold_low=0.8, threshold_high=0.2)


def test_density_config_rejects_equal_thresholds(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    with pytest.raises(ValueError, match="thresholds must satisfy"):
        ndvi_to_density_config(ndvi_tif, threshold_low=0.5, threshold_high=0.5)


def test_density_config_rejects_max_density_zero(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    with pytest.raises(ValueError, match="max_density_per_m2 must be positive"):
        ndvi_to_density_config(ndvi_tif, max_density_per_m2=0.0)


def test_density_config_rejects_max_density_negative(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    with pytest.raises(ValueError, match="max_density_per_m2 must be positive"):
        ndvi_to_density_config(ndvi_tif, max_density_per_m2=-1.0)


def test_density_config_density_multiplier_matches_arg(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif, max_density_per_m2=2.5)
    assert cfg["density_multiplier"] == pytest.approx(2.5)


def test_density_config_ndvi_image_path_is_string(tmp_path):
    ndvi_tif = tmp_path / "ndvi.tif"
    cfg = ndvi_to_density_config(ndvi_tif)
    assert isinstance(cfg["ndvi_image_path"], str)


# ---------------------------------------------------------------------------
# compute_ndvi — mocked subprocess
# ---------------------------------------------------------------------------


def test_compute_ndvi_calls_subprocess(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    with patch("blender_tools.ndvi_scatter.subprocess.run") as mock_run:
        result = compute_ndvi(red, nir, out)
    mock_run.assert_called_once()
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("check") is True
    assert kwargs.get("timeout") == 300


def test_compute_ndvi_returns_output_path(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    with patch("blender_tools.ndvi_scatter.subprocess.run"):
        result = compute_ndvi(red, nir, out)
    assert result == out


def test_compute_ndvi_propagates_subprocess_error(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    with patch("blender_tools.ndvi_scatter.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "gdal_calc.py")
        with pytest.raises(subprocess.CalledProcessError):
            compute_ndvi(red, nir, out)


def test_compute_ndvi_custom_timeout(tmp_path):
    red = tmp_path / "red.tif"
    nir = tmp_path / "nir.tif"
    out = tmp_path / "ndvi.tif"
    with patch("blender_tools.ndvi_scatter.subprocess.run") as mock_run:
        compute_ndvi(red, nir, out, timeout_seconds=60)
    assert mock_run.call_args.kwargs.get("timeout") == 60
