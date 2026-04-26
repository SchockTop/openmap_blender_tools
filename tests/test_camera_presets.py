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
                "shutter_open", "use_case"}
    for name, p in CAMERA_PRESETS.items():
        missing = required - set(p)
        assert not missing, f"preset {name!r} missing {missing}"


def test_get_preset_unknown_raises():
    from blender_tools.camera_presets import get_preset
    with pytest.raises(KeyError, match="unknown"):
        get_preset("does-not-exist")


def test_get_preset_returns_dict():
    from blender_tools.camera_presets import get_preset
    p = get_preset("cinematic-establishing")
    assert p["lens_mm"] == 85.0
    assert p["altitude_agl_m"] == 2000.0


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


def test_preset_altitudes_are_monotonically_distinct():
    """Sanity: each preset altitude is meaningfully different so renders differ."""
    from blender_tools.camera_presets import CAMERA_PRESETS
    alts = sorted(p["altitude_agl_m"] for p in CAMERA_PRESETS.values())
    # 1.7, 1.7, 80, 500, 2000, 4500 -- two entries share 1.7 but the rest differ
    distinct = set(alts)
    assert len(distinct) >= 5
