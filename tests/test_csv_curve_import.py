"""tests/test_csv_curve_import.py"""
import csv
from pathlib import Path
import pytest


def write_csv(path: Path, headers: list, rows: list):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# --- Header detection ---

def test_detect_wgs84_from_lat_lon():
    from blender_tools.csv_curve_import import detect_coordinate_system
    assert detect_coordinate_system(["lat", "lon", "alt"]) == "wgs84"


def test_detect_utm_from_easting_northing():
    from blender_tools.csv_curve_import import detect_coordinate_system
    assert detect_coordinate_system(["easting", "northing", "z"]) == "utm32n"


def test_detect_unknown_raises():
    from blender_tools.csv_curve_import import detect_coordinate_system
    with pytest.raises(ValueError):
        detect_coordinate_system(["foo", "bar"])


def test_detect_prefers_wgs84_when_both_present():
    from blender_tools.csv_curve_import import detect_coordinate_system
    assert detect_coordinate_system(["lat", "lon", "easting", "northing"]) == "wgs84"


# --- CSV reading ---

def test_read_path_csv_wgs84(tmp_path):
    from blender_tools.csv_curve_import import read_path_csv
    p = tmp_path / "wp.csv"
    write_csv(p, ["lat", "lon", "alt"],
              [{"lat": "48.137", "lon": "11.575", "alt": "520"},
               {"lat": "48.140", "lon": "11.580", "alt": "525"}])
    rows = read_path_csv(p)
    assert len(rows) == 2
    assert rows[0]["lat"] == 48.137
    assert rows[0]["alt"] == 520.0
    assert rows[0]["crs"] == "wgs84"


def test_read_path_csv_utm(tmp_path):
    from blender_tools.csv_curve_import import read_path_csv
    p = tmp_path / "utm.csv"
    write_csv(p, ["easting", "northing", "z", "heading"],
              [{"easting": "691000", "northing": "5334000", "z": "520", "heading": "45"},
               {"easting": "691100", "northing": "5334050", "z": "525", "heading": "60"}])
    rows = read_path_csv(p)
    assert rows[0]["utm_x"] == 691000.0
    assert rows[0]["heading"] == 45.0


def test_read_path_csv_optional_columns_default(tmp_path):
    from blender_tools.csv_curve_import import read_path_csv
    p = tmp_path / "minimal.csv"
    write_csv(p, ["lat", "lon"],
              [{"lat": "48", "lon": "11"}, {"lat": "48.1", "lon": "11.1"}])
    rows = read_path_csv(p)
    assert rows[0]["alt"] == 0.0
    assert rows[0]["heading"] is None
    assert rows[0]["time"] is None


# --- Bezier curve creation (mocked) ---

def test_csv_to_blender_curve_creates_bezier_with_correct_count(tmp_path, monkeypatch):
    from blender_tools import csv_curve_import
    from unittest.mock import MagicMock

    p = tmp_path / "wp.csv"
    write_csv(p, ["lat", "lon", "alt"],
              [{"lat": "48.137", "lon": "11.575", "alt": "520"},
               {"lat": "48.140", "lon": "11.580", "alt": "525"},
               {"lat": "48.143", "lon": "11.585", "alt": "530"}])

    fake_bpy = MagicMock()
    fake_curve_data = MagicMock()
    fake_spline = MagicMock()

    # Replicate Blender's pattern: spline starts with 1 point, .add(N-1) extends.
    add_history = []

    class BezierList(list):
        def add(self_inner, n):
            add_history.append(n)
            for _ in range(n):
                self_inner.append(MagicMock())

    bp_list = BezierList([MagicMock()])  # start with 1
    fake_spline.bezier_points = bp_list
    fake_curve_data.splines.new.return_value = fake_spline
    fake_bpy.data.curves.new.return_value = fake_curve_data
    fake_obj = MagicMock()
    fake_obj.data = fake_curve_data
    fake_bpy.data.objects.new.return_value = fake_obj
    monkeypatch.setattr(csv_curve_import, "_require_bpy", lambda: fake_bpy)

    csv_curve_import.csv_to_blender_curve(p, anchor_utm32n=(0, 0, 0))
    # 3 input rows -> add(2) called once.
    assert add_history == [2]
    # Must have linked into scene collection.
    fake_bpy.context.scene.collection.objects.link.assert_called_once()


# --- Attach helper ---

def test_attach_object_to_curve_speed_to_duration(monkeypatch):
    from blender_tools import csv_curve_import
    from unittest.mock import MagicMock
    obj = MagicMock()
    obj.type = "MESH"
    curve = MagicMock()
    curve.type = "CURVE"
    spline = MagicMock()
    bp0 = MagicMock()
    bp0.co.x = 0
    bp0.co.y = 0
    bp0.co.z = 0
    bp1 = MagicMock()
    bp1.co.x = 100
    bp1.co.y = 0
    bp1.co.z = 0
    spline.bezier_points = [bp0, bp1]
    curve.data.splines = [spline]
    curve.data.path_duration = 1
    fake_bpy = MagicMock()
    monkeypatch.setattr(csv_curve_import, "_require_bpy", lambda: fake_bpy)

    res = csv_curve_import.attach_object_to_curve(obj, curve, fps=25.0, speed_mps=10.0)
    # 100 m / 10 m/s = 10 s * 25 fps = 250 frames
    assert curve.data.path_duration == 250
    assert res["arc_length_m"] == 100.0


def test_attach_object_to_curve_rejects_non_curve():
    from blender_tools.csv_curve_import import attach_object_to_curve
    from unittest.mock import MagicMock
    not_curve = MagicMock()
    not_curve.type = "MESH"
    with pytest.raises(TypeError, match="not CURVE"):
        attach_object_to_curve(MagicMock(), not_curve)
