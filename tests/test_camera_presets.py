"""Unit tests for camera_presets - pure-Python with MagicMock for bpy."""
import pytest
from unittest.mock import MagicMock


def test_camera_presets_has_six_named():
    from blender_tools.camera_presets import CAMERA_PRESETS, list_presets
    expected = {"fpv-walk", "fpv-bike", "low-drone", "mid-drone",
                "cinematic-establishing", "aircraft-approach"}
    assert set(CAMERA_PRESETS) == expected
    assert set(list_presets()) == expected


def test_each_preset_has_required_fields():
    from blender_tools.camera_presets import CAMERA_PRESETS
    required = {"label", "altitude_agl_m", "speed_mps", "lens_mm",
                "sensor_width_mm", "banking_max_deg", "noise_amplitude_deg",
                "shutter_open", "tilt_pitch_deg", "use_case"}
    for name, p in CAMERA_PRESETS.items():
        missing = required - set(p)
        assert not missing, f"preset {name!r} missing {missing}"


def test_each_preset_has_tilt_pitch_deg():
    """Every preset must define a tilt_pitch_deg so the camera looks at a
    deliberate angle (negative = uplook, positive = downlook from horizon)."""
    from blender_tools.camera_presets import CAMERA_PRESETS
    expected = {
        "fpv-walk": -5.0,
        "fpv-bike": 0.0,
        "low-drone": -10.0,
        "mid-drone": -15.0,
        "cinematic-establishing": -45.0,
        "aircraft-approach": -45.0,
    }
    for name, want in expected.items():
        got = CAMERA_PRESETS[name].get("tilt_pitch_deg")
        assert got == want, f"preset {name!r}: tilt_pitch_deg={got!r}, want {want!r}"


def test_get_preset_unknown_raises():
    from blender_tools.camera_presets import get_preset
    with pytest.raises(KeyError, match="unknown"):
        get_preset("does-not-exist")


def test_get_preset_returns_dict():
    from blender_tools.camera_presets import get_preset
    p = get_preset("cinematic-establishing")
    assert p["lens_mm"] == 50.0
    assert p["altitude_agl_m"] == 800.0
    assert p["tilt_pitch_deg"] == -45.0


def test_default_preset_constant():
    from blender_tools.camera_presets import DEFAULT_PRESET, CAMERA_PRESETS
    assert DEFAULT_PRESET in CAMERA_PRESETS


@pytest.mark.parametrize("preset_name", [
    "fpv-walk", "fpv-bike", "low-drone", "mid-drone",
    "cinematic-establishing", "aircraft-approach"
])
def test_apply_camera_preset_sets_lens_sensor_clip(preset_name):
    from blender_tools.camera_presets import apply_camera_preset, get_preset
    cam = MagicMock(); cam.type = "CAMERA"
    cam.data = MagicMock()
    cam.parent = None
    cam.animation_data = None
    p = apply_camera_preset(cam, preset_name)
    assert cam.data.lens == p["lens_mm"]
    assert cam.data.sensor_width == p["sensor_width_mm"]
    assert cam.data.clip_end == 100_000.0
    # Low-AGL presets get small clip_start, high-AGL get 1.0.
    if p["altitude_agl_m"] < 50:
        assert cam.data.clip_start == 0.1
    else:
        assert cam.data.clip_start == 1.0
    # rotation_euler must have been set to (90 + tilt) degrees on X.
    import math
    expected_x = math.radians(90.0 + p["tilt_pitch_deg"])
    assert cam.rotation_euler == (expected_x, 0.0, 0.0)


def test_apply_camera_preset_lifts_rig_altitude():
    from blender_tools.camera_presets import apply_camera_preset
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    rig = MagicMock(); cam.parent = rig
    cam.animation_data = None
    apply_camera_preset(cam, "low-drone", terrain_z=520.0)
    # 520 + 80 = 600
    assert rig.location.z == 600.0


def test_apply_camera_preset_lifts_camera_when_no_parent():
    from blender_tools.camera_presets import apply_camera_preset
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    cam.parent = None
    cam.animation_data = None
    apply_camera_preset(cam, "aircraft-approach", terrain_z=100.0)
    # No parent -> camera itself is lifted; 100 + 4500 = 4600
    assert cam.location.z == 4600.0


def test_apply_camera_preset_rejects_non_camera():
    from blender_tools.camera_presets import apply_camera_preset
    obj = MagicMock(); obj.type = "MESH"
    with pytest.raises(TypeError, match="not CAMERA"):
        apply_camera_preset(obj, "fpv-walk")


def test_apply_camera_preset_returns_preset_dict():
    from blender_tools.camera_presets import apply_camera_preset
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    cam.parent = None
    cam.animation_data = None
    p = apply_camera_preset(cam, "mid-drone")
    assert p["lens_mm"] == 50.0
    assert p["speed_mps"] == 30.0


def test_apply_camera_preset_sets_motion_blur_when_scene_given():
    from blender_tools.camera_presets import apply_camera_preset
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    cam.parent = None
    cam.animation_data = None
    scene = MagicMock()
    apply_camera_preset(cam, "cinematic-establishing", scene=scene)
    assert scene.render.use_motion_blur is True
    assert scene.render.motion_blur_shutter == 0.5


def test_lift_curve_to_altitude_translates_all_points():
    """Helper must shift every control point so the mean lands at target_z."""
    from blender_tools.camera_presets import _lift_curve_to_altitude
    from unittest.mock import MagicMock
    # Fake spline with 3 bezier points at z=0, 10, 20 (mean=10).
    points = []
    for z in (0.0, 10.0, 20.0):
        p = MagicMock()
        p.co = MagicMock(); p.co.z = z
        p.handle_left = MagicMock(); p.handle_left.z = z - 1
        p.handle_right = MagicMock(); p.handle_right.z = z + 1
        points.append(p)
    spline = MagicMock(); spline.bezier_points = points; spline.points = []
    curve_obj = MagicMock(); curve_obj.data.splines = [spline]
    _lift_curve_to_altitude(curve_obj, 100.0)
    # Mean should now be 100. Original Z's were 0, 10, 20 -> after +90: 90, 100, 110. mean=100.
    assert points[0].co.z == 90.0
    assert points[1].co.z == 100.0
    assert points[2].co.z == 110.0
    # Handles also shifted.
    assert points[0].handle_left.z == 89.0
    assert points[0].handle_right.z == 91.0


def test_apply_camera_preset_lifts_curve_via_helper(monkeypatch):
    """When curve_obj is present, the curve-lift helper must be called."""
    from blender_tools import camera_presets
    from unittest.mock import MagicMock
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    cam.parent = None; cam.animation_data = None
    curve = MagicMock(); curve.type = "CURVE"
    curve.data.splines = []  # empty curve - lift is no-op but should still be called
    scene = MagicMock(); scene.render.fps = 25.0
    called_with = {}
    def fake_lift(c, z):
        called_with["curve"] = c; called_with["z"] = z
    monkeypatch.setattr(camera_presets, "_lift_curve_to_altitude", fake_lift)
    camera_presets.apply_camera_preset(cam, "low-drone", scene=scene,
                                        curve_obj=curve, terrain_z=520.0)
    assert called_with["curve"] is curve
    assert called_with["z"] == 600.0  # terrain_z 520 + low-drone altitude 80


def test_apply_camera_preset_removes_damped_track_so_tilt_applies(monkeypatch):
    """If a Damped Track constraint exists, it must be removed so rotation
    set by the preset isn't overridden."""
    from blender_tools import camera_presets
    from unittest.mock import MagicMock
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    cam.parent = None; cam.animation_data = None
    # Simulate a damped track constraint.
    constraint = MagicMock(); constraint.type = "DAMPED_TRACK"
    constraints_mock = MagicMock()
    constraints_mock.__iter__ = lambda self: iter([constraint])
    cam.constraints = constraints_mock
    camera_presets.apply_camera_preset(cam, "cinematic-establishing", terrain_z=520.0)
    constraints_mock.remove.assert_called_once_with(constraint)


def test_each_preset_has_curve_start_frame_pct():
    from blender_tools.camera_presets import CAMERA_PRESETS
    for name, p in CAMERA_PRESETS.items():
        pct = p.get("curve_start_frame_pct")
        assert pct is not None, f"{name!r} missing curve_start_frame_pct"
        assert 0.0 <= pct <= 1.0, f"{name!r} pct out of range: {pct}"

    # Verify monotonic ordering: fpv-walk earliest, aircraft latest.
    order = ["fpv-walk", "fpv-bike", "low-drone", "mid-drone",
             "cinematic-establishing", "aircraft-approach"]
    pcts = [CAMERA_PRESETS[n]["curve_start_frame_pct"] for n in order]
    for i in range(1, len(pcts)):
        assert pcts[i] >= pcts[i-1], f"non-monotonic: {pcts}"


def test_apply_camera_preset_calls_frame_set(monkeypatch):
    """When a curve is given, frame_set must be called with the per-preset offset."""
    from blender_tools import camera_presets
    from unittest.mock import MagicMock
    cam = MagicMock(); cam.type = "CAMERA"; cam.data = MagicMock()
    cam.parent = None; cam.animation_data = None
    cam.constraints = MagicMock(); cam.constraints.__iter__ = lambda s: iter([])
    curve = MagicMock(); curve.type = "CURVE"
    curve.data.splines = []
    curve.data.path_duration = 100
    scene = MagicMock(); scene.render.fps = 25.0
    camera_presets.apply_camera_preset(cam, "aircraft-approach", scene=scene,
                                        curve_obj=curve, terrain_z=520.0)
    # aircraft-approach has curve_start_frame_pct=0.85 -> eval_frame = 85
    scene.frame_set.assert_called_with(85)


def test_preset_altitudes_are_monotonically_distinct():
    """Sanity: each preset altitude is meaningfully different so renders differ."""
    from blender_tools.camera_presets import CAMERA_PRESETS
    alts = sorted(p["altitude_agl_m"] for p in CAMERA_PRESETS.values())
    # 1.7, 1.7, 80, 500, 2000, 4500 -- two entries share 1.7 but the rest differ
    distinct = set(alts)
    assert len(distinct) >= 5
