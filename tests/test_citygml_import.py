"""Unit tests for citygml_import.py.

Pure-Python helpers are fully tested without external deps. bpy-dependent code
uses a mock bpy fixture. External CLI code (citygml-tools) uses patched subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from blender_tools.citygml_import import (
    _citygml_tools_cmd,
    _collect_vertex_indices,
    _manual_cityjson_import,
    building_z_snap_offset,
    cityjson_to_blender,
    gml_to_cityjson,
    parse_citygml_lod_level,
)


# ---------------------------------------------------------------------------
# parse_citygml_lod_level — filename-based detection
# ---------------------------------------------------------------------------


def test_parse_lod_ldbv_filename(tmp_path):
    """LDBV-style filename `_lod2_` → 2."""
    p = tmp_path / "bayern_lod2_694_5337.gml"
    p.write_text("<dummy/>")
    assert parse_citygml_lod_level(p) == 2


def test_parse_lod_underscore_prefix(tmp_path):
    """Filename `_lod3_` → 3."""
    p = tmp_path / "city_lod3_buildings.gml"
    p.write_text("<dummy/>")
    assert parse_citygml_lod_level(p) == 3


def test_parse_lod_no_underscores_lod4(tmp_path):
    """Filename `lod4_building.gml` → 4 (no surrounding underscores needed)."""
    p = tmp_path / "lod4_building.gml"
    p.write_text("<dummy/>")
    assert parse_citygml_lod_level(p) == 4


def test_parse_lod_lod1(tmp_path):
    """Filename with lod1 → 1."""
    p = tmp_path / "export_lod1_2024.gml"
    p.write_text("<dummy/>")
    assert parse_citygml_lod_level(p) == 1


def test_parse_lod_from_file_content(tmp_path):
    """LoD not in filename but `lod="2"` present in file head → 2."""
    p = tmp_path / "buildings.gml"
    p.write_bytes(b'<?xml version="1.0"?><CityGML lod="2"><Building/></CityGML>')
    assert parse_citygml_lod_level(p) == 2


def test_parse_lod_from_file_content_lod3_text(tmp_path):
    """LoD embedded as lod3 text in file head → 3."""
    p = tmp_path / "nolevel.gml"
    p.write_bytes(b"<root><lod3Surface/></root>")
    assert parse_citygml_lod_level(p) == 3


def test_parse_lod_raises_when_indeterminate(tmp_path):
    """No LoD in filename or content → ValueError."""
    p = tmp_path / "nolevel.gml"
    p.write_bytes(b"<root><Building/></root>")
    with pytest.raises(ValueError, match="Cannot determine LoD level"):
        parse_citygml_lod_level(p)


def test_parse_lod_highest_wins_in_filename(tmp_path):
    """If multiple levels appear in name, the highest found first in search order wins."""
    # Search order is 4,3,2,1,0 — so lod3 in the name returns 3 even though lod2 also present.
    p = tmp_path / "lod3_lod2_mixed.gml"
    p.write_text("<dummy/>")
    assert parse_citygml_lod_level(p) == 3


# ---------------------------------------------------------------------------
# building_z_snap_offset
# ---------------------------------------------------------------------------


def test_snap_offset_building_below_terrain():
    """Building ground 10 m, terrain 12 m → offset +2 m."""
    assert building_z_snap_offset(10.0, 12.0) == pytest.approx(2.0)


def test_snap_offset_building_above_terrain():
    """Building ground 15 m, terrain 12 m → offset -3 m."""
    assert building_z_snap_offset(15.0, 12.0) == pytest.approx(-3.0)


def test_snap_offset_clamped_positive():
    """50 m upward mismatch → clamped to default +5 m."""
    assert building_z_snap_offset(0.0, 50.0) == pytest.approx(5.0)


def test_snap_offset_clamped_negative():
    """50 m downward mismatch → clamped to default -5 m."""
    assert building_z_snap_offset(50.0, 0.0) == pytest.approx(-5.0)


def test_snap_offset_custom_clamp_positive():
    """Custom clamp of 1.0 m — +10 m raw clamped to +1 m."""
    assert building_z_snap_offset(0.0, 10.0, clamp_meters=1.0) == pytest.approx(1.0)


def test_snap_offset_custom_clamp_negative():
    """Custom clamp of 1.0 m — -10 m raw clamped to -1 m."""
    assert building_z_snap_offset(10.0, 0.0, clamp_meters=1.0) == pytest.approx(-1.0)


def test_snap_offset_exact_match():
    """Building and terrain at same Z → offset 0."""
    assert building_z_snap_offset(100.0, 100.0) == pytest.approx(0.0)


def test_snap_offset_within_clamp():
    """3 m mismatch, clamp 5 m → passes through unchanged."""
    assert building_z_snap_offset(10.0, 13.0, clamp_meters=5.0) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# _citygml_tools_cmd
# ---------------------------------------------------------------------------


def test_cmd_non_docker_starts_with_citygml_tools(tmp_path):
    gml = tmp_path / "input.gml"
    out = tmp_path / "out.json"
    cmd = _citygml_tools_cmd([gml], out, use_docker=False)
    assert cmd[0] == "citygml-tools"
    assert cmd[1] == "to-cityjson"


def test_cmd_non_docker_includes_output(tmp_path):
    gml = tmp_path / "input.gml"
    out = tmp_path / "result.json"
    cmd = _citygml_tools_cmd([gml], out, use_docker=False)
    assert "--output" in cmd
    assert str(out) in cmd


def test_cmd_non_docker_includes_input_files(tmp_path):
    gml1 = tmp_path / "a.gml"
    gml2 = tmp_path / "b.gml"
    out = tmp_path / "out.json"
    cmd = _citygml_tools_cmd([gml1, gml2], out, use_docker=False)
    assert str(gml1) in cmd
    assert str(gml2) in cmd


def test_cmd_docker_starts_with_docker_run(tmp_path):
    gml = tmp_path / "input.gml"
    out = tmp_path / "out.json"
    # Docker mode requires paths relative to cwd; use cwd-relative tmp to keep it simple.
    cwd = Path.cwd()
    try:
        gml_rel = gml.relative_to(cwd)
        out_rel = out.relative_to(cwd)
    except ValueError:
        pytest.skip("tmp_path not under cwd — Docker path test requires relative paths")
    cmd = _citygml_tools_cmd([gml], out, use_docker=True)
    assert cmd[0] == "docker"
    assert cmd[1] == "run"
    assert "--rm" in cmd


def test_cmd_docker_mounts_cwd(tmp_path):
    """Docker command must contain -v <cwd>:/data."""
    cwd = Path.cwd()
    gml = cwd / "dummy_input.gml"
    out = cwd / "dummy_output.json"
    cmd = _citygml_tools_cmd([gml], out, use_docker=True)
    assert "-v" in cmd
    v_idx = cmd.index("-v")
    assert cmd[v_idx + 1] == f"{cwd}:/data"


def test_cmd_docker_translates_paths_to_data(tmp_path):
    """Docker command must translate file paths to /data/... form."""
    cwd = Path.cwd()
    gml = cwd / "test_input.gml"
    out = cwd / "test_output.json"
    cmd = _citygml_tools_cmd([gml], out, use_docker=True)
    assert any(arg.startswith("/data/") for arg in cmd if "input" in arg or "output" in arg)


# ---------------------------------------------------------------------------
# _collect_vertex_indices
# ---------------------------------------------------------------------------


def test_collect_flat_list():
    out: set[int] = set()
    _collect_vertex_indices([1, 2, 3], out)
    assert out == {1, 2, 3}


def test_collect_nested_list():
    out: set[int] = set()
    _collect_vertex_indices([[[0, 1, 2]], [[3, 4, 5]]], out)
    assert out == {0, 1, 2, 3, 4, 5}


def test_collect_mixed_depth():
    out: set[int] = set()
    _collect_vertex_indices([[0, [1, [2]]], 3], out)
    assert out == {0, 1, 2, 3}


def test_collect_single_int():
    out: set[int] = set()
    _collect_vertex_indices(7, out)
    assert out == {7}


def test_collect_empty_list():
    out: set[int] = set()
    _collect_vertex_indices([], out)
    assert out == set()


def test_collect_duplicates_deduped():
    out: set[int] = set()
    _collect_vertex_indices([[1, 2], [1, 3]], out)
    assert out == {1, 2, 3}


# ---------------------------------------------------------------------------
# gml_to_cityjson — mocked subprocess
# ---------------------------------------------------------------------------


def test_gml_to_cityjson_calls_subprocess(tmp_path):
    gml = tmp_path / "test.gml"
    out = tmp_path / "out.json"
    with patch("blender_tools.citygml_import.subprocess.run") as mock_run:
        result = gml_to_cityjson([gml], out)
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("check") is True
    assert call_kwargs.kwargs.get("timeout") == 600


def test_gml_to_cityjson_returns_output_path(tmp_path):
    gml = tmp_path / "test.gml"
    out = tmp_path / "out.json"
    with patch("blender_tools.citygml_import.subprocess.run"):
        result = gml_to_cityjson([gml], out)
    assert result == out


def test_gml_to_cityjson_propagates_subprocess_error(tmp_path):
    gml = tmp_path / "test.gml"
    out = tmp_path / "out.json"
    with patch("blender_tools.citygml_import.subprocess.run") as mock_run:
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "citygml-tools")
        with pytest.raises(subprocess.CalledProcessError):
            gml_to_cityjson([gml], out)


def test_gml_to_cityjson_custom_timeout(tmp_path):
    gml = tmp_path / "test.gml"
    out = tmp_path / "out.json"
    with patch("blender_tools.citygml_import.subprocess.run") as mock_run:
        gml_to_cityjson([gml], out, timeout_seconds=120)
    assert mock_run.call_args.kwargs.get("timeout") == 120


# ---------------------------------------------------------------------------
# cityjson_to_blender — mocked bpy
# ---------------------------------------------------------------------------


def _make_mock_bpy(up3date_available: bool = True) -> MagicMock:
    """Build a minimal mock bpy module."""
    bpy = MagicMock()

    # Scene mock with a dict-like interface for scene properties.
    scene = MagicMock()
    scene.__setitem__ = MagicMock()
    scene.__getitem__ = MagicMock()
    bpy.context.scene = scene

    # Collections — coll.objects must support .link() so keep as MagicMock.
    coll = MagicMock()
    bpy.data.collections.get.return_value = None
    bpy.data.collections.new.return_value = coll

    if not up3date_available:
        bpy.ops.up3date.import_cityjson.side_effect = AttributeError("up3date not installed")

    return bpy


def test_cityjson_to_blender_sets_anchor(tmp_path):
    """cityjson_to_blender stores anchor into scene props."""
    cityjson_path = tmp_path / "city.json"
    cityjson_path.write_text(json.dumps({"CityObjects": {}, "vertices": []}))

    mock_bpy = _make_mock_bpy(up3date_available=True)
    # Make up3date import succeed without actually importing anything.
    mock_bpy.ops.up3date.import_cityjson.return_value = None

    with patch("blender_tools.citygml_import._require_bpy", return_value=mock_bpy):
        cityjson_to_blender(cityjson_path, anchor_utm32n=(100.0, 200.0, 50.0))

    mock_bpy.context.scene.__setitem__.assert_called_with(
        "utm32n_anchor", [100.0, 200.0, 50.0]
    )


def test_cityjson_to_blender_creates_collection(tmp_path):
    """Collection 'Buildings' is created when not already present."""
    cityjson_path = tmp_path / "city.json"
    cityjson_path.write_text(json.dumps({"CityObjects": {}, "vertices": []}))

    mock_bpy = _make_mock_bpy(up3date_available=True)
    mock_bpy.ops.up3date.import_cityjson.return_value = None

    with patch("blender_tools.citygml_import._require_bpy", return_value=mock_bpy):
        cityjson_to_blender(cityjson_path)

    mock_bpy.data.collections.new.assert_called_once_with("Buildings")


def test_cityjson_to_blender_fallback_fires_when_up3date_missing(tmp_path):
    """When Up3date isn't available, manual CityJSON import runs without error."""
    cityjson_path = tmp_path / "city.json"
    # Minimal valid CityJSON with one Building.
    city_data = {
        "CityObjects": {
            "B1": {
                "type": "Building",
                "geometry": [{"boundaries": [[[0, 1, 2]]]}],
            }
        },
        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    }
    cityjson_path.write_text(json.dumps(city_data))

    mock_bpy = _make_mock_bpy(up3date_available=False)

    # Prepare a minimal mesh mock for from_pydata calls.
    mesh_mock = MagicMock()
    obj_mock = MagicMock()
    coll_mock = MagicMock()
    # coll.objects must support .link() — keep as MagicMock (default).

    mock_bpy.data.meshes.new.return_value = mesh_mock
    mock_bpy.data.objects.new.return_value = obj_mock
    mock_bpy.data.collections.new.return_value = coll_mock

    with patch("blender_tools.citygml_import._require_bpy", return_value=mock_bpy):
        result = cityjson_to_blender(cityjson_path)

    # One building was found → one object created.
    mock_bpy.data.meshes.new.assert_called_once()
    mock_bpy.data.objects.new.assert_called_once()
    assert result == [obj_mock]


def test_cityjson_to_blender_skips_non_buildings(tmp_path):
    """CityObjects of type != 'Building' are ignored in the manual fallback."""
    cityjson_path = tmp_path / "city.json"
    city_data = {
        "CityObjects": {
            "R1": {"type": "Road", "geometry": [{"boundaries": [[0, 1]]}]},
            "B1": {
                "type": "Building",
                "geometry": [{"boundaries": [[[0, 1, 2]]]}],
            },
        },
        "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    }
    cityjson_path.write_text(json.dumps(city_data))

    mock_bpy = _make_mock_bpy(up3date_available=False)
    mesh_mock = MagicMock()
    obj_mock = MagicMock()
    coll_mock = MagicMock()
    # coll.objects must support .link() — keep as MagicMock (default).

    mock_bpy.data.meshes.new.return_value = mesh_mock
    mock_bpy.data.objects.new.return_value = obj_mock
    mock_bpy.data.collections.new.return_value = coll_mock

    with patch("blender_tools.citygml_import._require_bpy", return_value=mock_bpy):
        result = cityjson_to_blender(cityjson_path)

    # Only one Building should be created.
    assert mock_bpy.data.meshes.new.call_count == 1


def test_cityjson_to_blender_raises_without_bpy(tmp_path, monkeypatch):
    """cityjson_to_blender raises RuntimeError when bpy cannot be imported."""
    cityjson_path = tmp_path / "city.json"
    cityjson_path.write_text("{}")

    # Patch _require_bpy to raise RuntimeError as the real one would.
    with patch(
        "blender_tools.citygml_import._require_bpy",
        side_effect=RuntimeError("requires bpy"),
    ):
        with pytest.raises(RuntimeError, match="requires bpy"):
            cityjson_to_blender(cityjson_path)


# ---------------------------------------------------------------------------
# gml_to_cityjson_pure — pure-Python LDBV LoD2 converter
# ---------------------------------------------------------------------------

import textwrap

LDBV_LOD2_SAMPLE = textwrap.dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<core:CityModel xmlns:core="http://www.opengis.net/citygml/2.0"
                xmlns:bldg="http://www.opengis.net/citygml/building/2.0"
                xmlns:gml="http://www.opengis.net/gml">
  <core:cityObjectMember>
    <bldg:Building gml:id="B1">
      <bldg:lod2Solid>
        <gml:Solid>
          <gml:exterior>
            <gml:CompositeSurface>
              <gml:surfaceMember>
                <gml:Polygon>
                  <gml:exterior>
                    <gml:LinearRing>
                      <gml:posList srsDimension="3">
                        691000 5334000 520
                        691010 5334000 520
                        691010 5334010 520
                        691000 5334010 520
                        691000 5334000 520
                      </gml:posList>
                    </gml:LinearRing>
                  </gml:exterior>
                </gml:Polygon>
              </gml:surfaceMember>
            </gml:CompositeSurface>
          </gml:exterior>
        </gml:Solid>
      </bldg:lod2Solid>
    </bldg:Building>
  </core:cityObjectMember>
</core:CityModel>
""")


def test_gml_to_cityjson_pure_parses_one_building(tmp_path):
    from blender_tools.citygml_import import gml_to_cityjson_pure
    gml = tmp_path / "sample.gml"
    gml.write_text(LDBV_LOD2_SAMPLE, encoding="utf-8")
    out = tmp_path / "sample.json"
    result = gml_to_cityjson_pure([gml], out)
    assert result == out
    cj = json.loads(out.read_text(encoding="utf-8"))
    assert cj["type"] == "CityJSON"
    assert cj["version"] in {"1.0", "1.1", "2.0"}
    assert len(cj["CityObjects"]) == 1
    assert "B1" in cj["CityObjects"]
    assert cj["CityObjects"]["B1"]["type"] == "Building"
    assert len(cj["vertices"]) >= 4  # 4 unique XY corners (last == first dropped)
    geom = cj["CityObjects"]["B1"]["geometry"][0]
    assert geom["type"] == "Solid"
    assert geom["lod"] in {"2", "2.0", 2}
    boundaries = geom["boundaries"]
    assert isinstance(boundaries, list) and len(boundaries) >= 1


def test_gml_to_cityjson_pure_real_ldbv(tmp_path):
    from blender_tools.citygml_import import gml_to_cityjson_pure
    src = Path("../OpenMap_Workflow/data/raw/lod2/690_5334.gml")
    if not src.exists():
        pytest.skip("LDBV LoD2 sample not downloaded")
    out = tmp_path / "muc.json"
    gml_to_cityjson_pure([src], out)
    cj = json.loads(out.read_text(encoding="utf-8"))
    assert len(cj["CityObjects"]) > 100, len(cj["CityObjects"])
    assert len(cj["vertices"]) > 1000
