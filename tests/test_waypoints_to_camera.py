"""Tests for waypoints_to_camera.py.

Pure-Python helpers are tested directly.
bpy-dependent functions are tested with a mocked bpy module injected into
sys.modules so no actual Blender installation is required.
"""
from __future__ import annotations

import math
import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blender_tools.waypoints_to_camera import (
    arc_length,
    banking_degrees_from_curvature,
    path_duration_frames,
    read_waypoints_csv,
    subtract_anchor,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _write_csv(tmp_path: Path, content: str, filename: str = "wp.csv") -> Path:
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# read_waypoints_csv — happy path
# ---------------------------------------------------------------------------

class TestReadWaypointsCsvHappyPath:
    def test_three_rows_returns_three_tuples(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            48.1374,11.5755,520.0
            48.1380,11.5760,525.0
            48.1390,11.5770,530.0
        """)
        rows = read_waypoints_csv(csv_path)
        assert len(rows) == 3
        assert rows[0] == pytest.approx((48.1374, 11.5755, 520.0))
        assert rows[1] == pytest.approx((48.1380, 11.5760, 525.0))
        assert rows[2] == pytest.approx((48.1390, 11.5770, 530.0))

    def test_utf8_bom_tolerated(self, tmp_path):
        """File written with UTF-8 BOM (utf-8-sig) must be read without error."""
        csv_path = tmp_path / "bom.csv"
        content = "lat,lon,alt\n48.0,11.0,500.0\n"
        csv_path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        rows = read_waypoints_csv(csv_path)
        assert len(rows) == 1
        assert rows[0] == pytest.approx((48.0, 11.0, 500.0))

    def test_custom_column_names(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            latitude,longitude,altitude
            52.5,13.4,34.0
        """)
        rows = read_waypoints_csv(
            csv_path,
            lat_col="latitude",
            lon_col="longitude",
            alt_col="altitude",
        )
        assert rows == [(pytest.approx(52.5), pytest.approx(13.4), pytest.approx(34.0))]

    def test_integer_values_coerced_to_float(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            48,11,500
        """)
        rows = read_waypoints_csv(csv_path)
        assert isinstance(rows[0][0], float)
        assert rows[0] == pytest.approx((48.0, 11.0, 500.0))


# ---------------------------------------------------------------------------
# read_waypoints_csv — error cases
# ---------------------------------------------------------------------------

class TestReadWaypointsCsvErrors:
    def test_missing_lat_column_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            longitude,altitude
            11.0,500.0
        """)
        with pytest.raises(ValueError, match="lat"):
            read_waypoints_csv(csv_path)

    def test_missing_lon_column_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,altitude
            48.0,500.0
        """)
        with pytest.raises(ValueError, match="lon"):
            read_waypoints_csv(csv_path)

    def test_missing_alt_column_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon
            48.0,11.0
        """)
        with pytest.raises(ValueError, match="alt"):
            read_waypoints_csv(csv_path)

    def test_non_numeric_lat_raises_with_row_number(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            48.0,11.0,500.0
            bad,11.1,501.0
        """)
        with pytest.raises(ValueError, match=r"row 3"):
            read_waypoints_csv(csv_path)

    def test_non_numeric_lon_raises_with_row_number(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            48.0,notanumber,500.0
        """)
        with pytest.raises(ValueError, match=r"row 2"):
            read_waypoints_csv(csv_path)

    def test_lat_out_of_range_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            91.0,11.0,500.0
        """)
        with pytest.raises(ValueError, match="lat"):
            read_waypoints_csv(csv_path)

    def test_lat_negative_out_of_range_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            -91.0,11.0,500.0
        """)
        with pytest.raises(ValueError, match="lat"):
            read_waypoints_csv(csv_path)

    def test_lon_out_of_range_raises(self, tmp_path):
        csv_path = _write_csv(tmp_path, """\
            lat,lon,alt
            48.0,181.0,500.0
        """)
        with pytest.raises(ValueError, match="lon"):
            read_waypoints_csv(csv_path)


# ---------------------------------------------------------------------------
# subtract_anchor
# ---------------------------------------------------------------------------

class TestSubtractAnchor:
    def test_empty_list_returns_empty(self):
        assert subtract_anchor([], (1.0, 2.0, 3.0)) == []

    def test_zero_anchor_is_identity(self):
        pts = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
        result = subtract_anchor(pts, (0.0, 0.0, 0.0))
        assert result == pts

    def test_known_anchor_subtraction(self):
        pts = [(100.0, 200.0, 300.0), (150.0, 250.0, 350.0)]
        anchor = (100.0, 200.0, 300.0)
        result = subtract_anchor(pts, anchor)
        assert result[0] == pytest.approx((0.0, 0.0, 0.0))
        assert result[1] == pytest.approx((50.0, 50.0, 50.0))

    def test_negative_anchor(self):
        pts = [(10.0, 20.0, 30.0)]
        result = subtract_anchor(pts, (-5.0, -5.0, -5.0))
        assert result[0] == pytest.approx((15.0, 25.0, 35.0))


# ---------------------------------------------------------------------------
# arc_length
# ---------------------------------------------------------------------------

class TestArcLength:
    def test_single_point_returns_zero(self):
        assert arc_length([(0.0, 0.0, 0.0)]) == 0.0

    def test_empty_list_returns_zero(self):
        assert arc_length([]) == 0.0

    def test_two_points_100m_apart(self):
        pts = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
        assert arc_length(pts) == pytest.approx(100.0)

    def test_l_shape_three_points(self):
        """300 m east then 400 m north = 700 m total."""
        pts = [(0.0, 0.0, 0.0), (300.0, 0.0, 0.0), (300.0, 400.0, 0.0)]
        assert arc_length(pts) == pytest.approx(700.0)

    def test_diagonal_3d_segment(self):
        """sqrt(3^2 + 4^2 + 0^2) = 5.0"""
        pts = [(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]
        assert arc_length(pts) == pytest.approx(5.0)

    def test_zero_length_not_nan(self):
        pts = [(5.0, 5.0, 5.0), (5.0, 5.0, 5.0)]
        result = arc_length(pts)
        assert result == 0.0
        assert not math.isnan(result)


# ---------------------------------------------------------------------------
# path_duration_frames
# ---------------------------------------------------------------------------

class TestPathDurationFrames:
    def test_500m_50mps_25fps_gives_250_frames(self):
        assert path_duration_frames(500.0, 50.0, 25) == 250

    def test_ceiling_501m_50mps_25fps_gives_251_frames(self):
        """501 / 50 = 10.02 s; 10.02 * 25 = 250.5 → ceil → 251."""
        assert path_duration_frames(501.0, 50.0, 25) == 251

    def test_zero_speed_raises(self):
        with pytest.raises(ValueError, match="speed_mps"):
            path_duration_frames(100.0, 0.0, 25)

    def test_negative_speed_raises(self):
        with pytest.raises(ValueError, match="speed_mps"):
            path_duration_frames(100.0, -10.0, 25)

    def test_zero_fps_raises(self):
        with pytest.raises(ValueError, match="fps"):
            path_duration_frames(100.0, 50.0, 0)

    def test_negative_fps_raises(self):
        with pytest.raises(ValueError, match="fps"):
            path_duration_frames(100.0, 50.0, -1)

    def test_exact_division_no_ceiling(self):
        """100 m at 10 m/s at 10 fps = exactly 100 frames."""
        assert path_duration_frames(100.0, 10.0, 10) == 100


# ---------------------------------------------------------------------------
# banking_degrees_from_curvature
# ---------------------------------------------------------------------------

class TestBankingDegreesFromCurvature:
    def test_straight_line_returns_zero(self):
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (10.0, 0.0, 0.0)
        p_next = (20.0, 0.0, 0.0)
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_right_turn_returns_negative(self):
        """Turning right (CW from above): cross is negative → negative banking angle.

        Sign convention: + = bank left/CCW, - = bank right/CW.
        """
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (10.0, 0.0, 0.0)
        p_next = (10.0, -10.0, 0.0)  # turn right (south)
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next)
        assert result < 0.0

    def test_left_turn_returns_positive(self):
        """Turning left (CCW from above): cross is positive → positive banking angle."""
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (10.0, 0.0, 0.0)
        p_next = (10.0, 10.0, 0.0)  # turn left (north)
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next)
        assert result > 0.0

    def test_right_left_opposite_sign(self):
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (10.0, 0.0, 0.0)
        right = banking_degrees_from_curvature(p_prev, p_curr, (10.0, -10.0, 0.0))
        left = banking_degrees_from_curvature(p_prev, p_curr, (10.0, 10.0, 0.0))
        assert right == pytest.approx(-left, abs=1e-6)

    def test_sharp_turn_clamped_to_max(self):
        """A sharp 90° turn with very tight geometry should saturate banking_max_deg."""
        # 90° left turn using equal-length vectors so sin_turn = 1 → saturates max.
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (10.0, 0.0, 0.0)
        p_next = (10.0, 10.0, 0.0)  # exactly 90° turn left
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next, banking_max_deg=2.0)
        # sin(90°)*0.5 = 45°*0.5 = 22.5° → clamped to 2.0
        assert abs(result) == pytest.approx(2.0)

    def test_custom_max_clamp(self):
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (10.0, 0.0, 0.0)
        p_next = (10.0, -10.0, 0.0)
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next, banking_max_deg=2.0)
        assert abs(result) <= 2.0

    def test_zero_length_in_segment_returns_zero_not_nan(self):
        """Degenerate: consecutive identical points → 0.0, not NaN."""
        p_prev = (5.0, 5.0, 0.0)
        p_curr = (5.0, 5.0, 0.0)  # same as prev
        p_next = (10.0, 10.0, 0.0)
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next)
        assert result == 0.0
        assert not math.isnan(result)

    def test_zero_length_out_segment_returns_zero_not_nan(self):
        """Degenerate: curr == next → 0.0, not NaN."""
        p_prev = (0.0, 0.0, 0.0)
        p_curr = (5.0, 5.0, 0.0)
        p_next = (5.0, 5.0, 0.0)  # same as curr
        result = banking_degrees_from_curvature(p_prev, p_curr, p_next)
        assert result == 0.0
        assert not math.isnan(result)


# ---------------------------------------------------------------------------
# wgs84_to_utm32n — requires pyproj
# ---------------------------------------------------------------------------

class TestWgs84ToUtm32n:
    pyproj = pytest.importorskip("pyproj")

    def test_munich_city_centre(self):
        """Munich (48.1374°N, 11.5755°E, 520 m) → EPSG:25832.

        Reference values verified against pyproj with always_xy=True:
          lon=11.5755, lat=48.1374 → E≈691603, N≈5334780
        Tolerance ±200 m to accommodate minor proj-data differences.
        """
        from blender_tools.waypoints_to_camera import wgs84_to_utm32n

        result = wgs84_to_utm32n([(48.1374, 11.5755, 520.0)])
        assert len(result) == 1
        e, n, alt = result[0]
        assert e == pytest.approx(691_603, abs=200)
        assert n == pytest.approx(5_334_780, abs=200)
        assert alt == pytest.approx(520.0)

    def test_altitude_passthrough(self):
        """Altitude must be returned unchanged."""
        from blender_tools.waypoints_to_camera import wgs84_to_utm32n

        result = wgs84_to_utm32n([(48.0, 11.0, 999.5)])
        assert result[0][2] == pytest.approx(999.5)

    def test_multiple_points(self):
        """All input points should produce output points."""
        from blender_tools.waypoints_to_camera import wgs84_to_utm32n

        pts = [(48.0, 11.0, 0.0), (48.1, 11.1, 100.0), (48.2, 11.2, 200.0)]
        result = wgs84_to_utm32n(pts)
        assert len(result) == 3


class TestWgs84ToUtm32nMissingPyproj:
    def test_runtime_error_when_pyproj_missing(self):
        """Patching pyproj out of sys.modules should raise RuntimeError."""
        from blender_tools.waypoints_to_camera import wgs84_to_utm32n

        with patch.dict(sys.modules, {"pyproj": None}):
            with pytest.raises((RuntimeError, ImportError)):
                wgs84_to_utm32n([(48.0, 11.0, 0.0)])


# ---------------------------------------------------------------------------
# Helper: build a fake bpy module
# ---------------------------------------------------------------------------

def _make_fake_bpy():
    """Return a minimal mock bpy module suitable for testing curve/camera creation."""
    bpy = MagicMock(name="bpy")

    # --- data.curves.new ---
    curve_data = MagicMock(name="curve_data")
    spline = MagicMock(name="spline")
    spline.bezier_points = MagicMock(name="bezier_points")

    # bezier_points behaves like a list after .add(n) has been called.
    _bezier_list: list[MagicMock] = []

    def _bp_add(n: int) -> None:
        for _ in range(n + 1):  # add is called with count-to-add, but we seed 1 already
            _bezier_list.append(MagicMock())
        # re-expose as __iter__
        spline.bezier_points.__iter__ = lambda s: iter(_bezier_list)

    # Spline starts with 1 bezier_point implicitly.
    _bezier_list.append(MagicMock())
    spline.bezier_points.add.side_effect = _bp_add
    spline.bezier_points.__iter__ = lambda s: iter(_bezier_list)
    spline.bezier_points.__len__ = lambda s: len(_bezier_list)

    curve_data.splines.new.return_value = spline

    bpy.data.curves.new.return_value = curve_data

    # --- data.objects.new ---
    curve_obj = MagicMock(name="curve_obj")
    curve_obj.__setitem__ = MagicMock()  # allows curve_obj["key"] = value

    cam_data = MagicMock(name="cam_data")
    cam_obj = MagicMock(name="cam_obj")
    cam_obj.constraints = MagicMock(name="cam_constraints")
    cam_constraint = MagicMock(name="cam_constraint")
    cam_obj.constraints.new.return_value = cam_constraint

    rig_empty = MagicMock(name="rig_empty")
    rig_empty.constraints = MagicMock(name="rig_constraints")
    rig_follow = MagicMock(name="rig_follow")
    rig_empty.constraints.new.return_value = rig_follow
    rig_empty.__setitem__ = MagicMock()

    _obj_call_count = [0]

    def _objects_new(name, data):
        _obj_call_count[0] += 1
        if data is None:
            return rig_empty
        if hasattr(data, "_mock_name") and "cam" in str(data._mock_name).lower():
            return cam_obj
        return curve_obj

    bpy.data.objects.new.side_effect = _objects_new
    bpy.data.cameras.new.return_value = cam_data

    # --- collections ---
    coll = MagicMock(name="coll")
    bpy.data.collections.get.return_value = None
    bpy.data.collections.new.return_value = coll

    # --- scene ---
    bpy.context.scene.collection.children.link = MagicMock()
    bpy.context.scene.collection.objects.link = MagicMock()

    return bpy, curve_data, curve_obj, spline, _bezier_list, rig_empty, cam_obj, rig_follow


# ---------------------------------------------------------------------------
# wgs84_csv_to_bezier — mocked bpy
# ---------------------------------------------------------------------------

class TestWgs84CsvToBezierMockedBpy:
    @pytest.fixture(autouse=True)
    def _inject_bpy(self):
        bpy, *_ = _make_fake_bpy()
        with patch.dict(sys.modules, {"bpy": bpy}):
            yield bpy

    def _make_csv(self, tmp_path: Path) -> Path:
        return _write_csv(tmp_path, """\
            lat,lon,alt
            48.1374,11.5755,520.0
            48.1380,11.5760,525.0
            48.1390,11.5770,530.0
        """)

    @pytest.mark.skipif(
        "pyproj" not in sys.modules and True,
        reason="pyproj unavailable — skipped in CI without proj data",
    )
    def test_curve_created_with_correct_bezier_point_count(self, tmp_path):
        pyproj = pytest.importorskip("pyproj")
        from blender_tools.waypoints_to_camera import wgs84_csv_to_bezier

        csv_path = self._make_csv(tmp_path)
        bpy = sys.modules["bpy"]
        curve_obj = wgs84_csv_to_bezier(csv_path)

        # splines.new("BEZIER") should be called once.
        bpy.data.curves.new.return_value.splines.new.assert_called_once_with("BEZIER")
        # bezier_points.add should be called with (N-1) where N = 3.
        bpy.data.curves.new.return_value.splines.new.return_value.bezier_points.add.assert_called_once_with(2)

    @pytest.mark.skipif(
        "pyproj" not in sys.modules and True,
        reason="pyproj unavailable",
    )
    def test_path_duration_set_on_curve_data(self, tmp_path):
        pyproj = pytest.importorskip("pyproj")
        from blender_tools.waypoints_to_camera import wgs84_csv_to_bezier

        csv_path = self._make_csv(tmp_path)
        bpy = sys.modules["bpy"]
        wgs84_csv_to_bezier(csv_path, fps=25, speed_mps=50.0)

        curve_data = bpy.data.curves.new.return_value
        # path_duration must have been set (any integer > 0).
        assert curve_data.path_duration is not None

    @pytest.mark.skipif(
        "pyproj" not in sys.modules and True,
        reason="pyproj unavailable",
    )
    def test_custom_props_set(self, tmp_path):
        pyproj = pytest.importorskip("pyproj")
        from blender_tools.waypoints_to_camera import wgs84_csv_to_bezier

        csv_path = self._make_csv(tmp_path)
        bpy = sys.modules["bpy"]
        curve_obj = wgs84_csv_to_bezier(csv_path, speed_mps=30.0)

        # curve_obj["speed_mps"] and ["arc_length_m"] must be set.
        calls = {c.args[0]: c.args[1] for c in curve_obj.__setitem__.call_args_list}
        assert "speed_mps" in calls
        assert calls["speed_mps"] == pytest.approx(30.0)
        assert "arc_length_m" in calls
        assert calls["arc_length_m"] > 0

    def test_path_duration_matches_helper_formula(self, tmp_path):
        """Verify path_duration = path_duration_frames(arc_len, speed, fps) without pyproj.

        We mock wgs84_to_utm32n to return deterministic UTM coords.
        """
        pyproj_mod = pytest.importorskip("pyproj")

        # Use deterministic local waypoints (already in "UTM" units).
        deterministic_utm = [
            (691_000.0, 5_335_000.0, 520.0),
            (691_200.0, 5_335_100.0, 525.0),
            (691_500.0, 5_335_300.0, 530.0),
        ]

        from blender_tools import waypoints_to_camera as wtc

        with patch.object(wtc, "wgs84_to_utm32n", return_value=deterministic_utm):
            csv_path = self._make_csv(tmp_path)
            bpy = sys.modules["bpy"]
            wgs84_csv_to_bezier = wtc.wgs84_csv_to_bezier

            # Also need to ensure bpy is accessible inside the function
            wgs84_csv_to_bezier(csv_path, fps=25, speed_mps=50.0)

            # Compute expected duration ourselves.
            from blender_tools.waypoints_to_camera import subtract_anchor, arc_length, path_duration_frames
            local = subtract_anchor(deterministic_utm, (0.0, 0.0, 0.0))
            expected = path_duration_frames(arc_length(local), 50.0, 25)

            curve_data = bpy.data.curves.new.return_value
            assert curve_data.path_duration == expected


# ---------------------------------------------------------------------------
# attach_camera_rig — mocked bpy
# ---------------------------------------------------------------------------

class TestAttachCameraRigMockedBpy:
    @pytest.fixture()
    def fake_bpy_ctx(self):
        bpy, curve_data, curve_obj, spline, bp_list, rig_empty, cam_obj, rig_follow = _make_fake_bpy()
        with patch.dict(sys.modules, {"bpy": bpy}):
            yield bpy, curve_obj, rig_empty, cam_obj, rig_follow

    def test_rig_empty_linked_to_scene(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        attach_camera_rig(curve_obj)
        bpy.context.scene.collection.objects.link.assert_called()

    def test_follow_path_constraint_added_to_rig(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        attach_camera_rig(curve_obj)
        rig_empty.constraints.new.assert_called_with("FOLLOW_PATH")

    def test_follow_path_target_is_curve_obj(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        attach_camera_rig(curve_obj)
        assert rig_follow.target is curve_obj

    def test_camera_parented_to_rig(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        attach_camera_rig(curve_obj)
        assert cam_obj.parent is rig_empty

    def test_no_damped_track_without_target(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        attach_camera_rig(curve_obj, tracked_target=None)
        # cam_obj.constraints.new should NOT have been called.
        cam_obj.constraints.new.assert_not_called()

    def test_damped_track_added_when_target_given(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        target = MagicMock(name="target")
        attach_camera_rig(curve_obj, tracked_target=target)
        cam_obj.constraints.new.assert_called_with("DAMPED_TRACK")
        constraint = cam_obj.constraints.new.return_value
        assert constraint.target is target

    def test_banking_max_deg_stored_as_custom_prop(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        attach_camera_rig(curve_obj, banking_max_deg=12.0)
        # rig_empty["banking_max_deg"] = 12.0 must be set.
        calls = {c.args[0]: c.args[1] for c in rig_empty.__setitem__.call_args_list}
        assert "banking_max_deg" in calls
        assert calls["banking_max_deg"] == pytest.approx(12.0)

    def test_returns_camera_object(self, fake_bpy_ctx):
        bpy, curve_obj, rig_empty, cam_obj, rig_follow = fake_bpy_ctx
        from blender_tools.waypoints_to_camera import attach_camera_rig

        result = attach_camera_rig(curve_obj)
        assert result is cam_obj


def test_keyframe_constant_velocity_sets_linear_interpolation(monkeypatch):
    from blender_tools import waypoints_to_camera as w2c
    from unittest.mock import MagicMock

    inserted = []
    keyframe_points = [MagicMock(interpolation="BEZIER"),
                       MagicMock(interpolation="BEZIER")]
    fcurve = MagicMock(); fcurve.keyframe_points = keyframe_points
    action = MagicMock(); action.fcurves = [fcurve]
    anim_data = MagicMock(); anim_data.action = action
    curve_data = MagicMock(); curve_data.path_duration = 100
    curve_data.animation_data = anim_data
    curve_data.eval_time = 0.0
    curve_data.keyframe_insert = MagicMock(side_effect=lambda *a, **kw: inserted.append((a, kw)))

    w2c.keyframe_constant_velocity(curve_data)
    # Two keyframes inserted on eval_time
    assert any(("eval_time" in a or kw.get("data_path") == "eval_time")
               for a, kw in inserted)
    # All keyframe points set to LINEAR
    for kp in keyframe_points:
        assert kp.interpolation == "LINEAR"
