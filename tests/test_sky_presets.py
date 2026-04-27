"""Unit tests for sky_presets — pure-Python with MagicMock for bpy."""
from unittest.mock import MagicMock
import pytest


def test_six_named_presets():
    from blender_tools.sky_presets import SKY_PRESETS, list_sky_presets
    expected = {"noon", "golden-hour", "blue-hour", "dawn", "overcast", "afternoon"}
    assert set(SKY_PRESETS) == expected
    assert set(list_sky_presets()) == expected


def test_required_fields_in_each_preset():
    from blender_tools.sky_presets import SKY_PRESETS
    required = {"label", "sun_pitch_deg", "sun_azimuth_deg", "sun_energy",
                "sun_color_rgb", "sky_strength", "sky_air_density",
                "exposure_offset"}
    for name, p in SKY_PRESETS.items():
        missing = required - set(p)
        assert not missing, f"sky preset {name!r} missing {missing}"


def test_get_sky_preset_unknown_raises():
    from blender_tools.sky_presets import get_sky_preset
    with pytest.raises(KeyError, match="unknown"):
        get_sky_preset("does-not-exist")


def test_apply_sky_preset_sets_sun_attributes():
    from blender_tools.sky_presets import apply_sky_preset
    sun = MagicMock(); sun.type = "LIGHT"
    sun.data = MagicMock(); sun.data.type = "SUN"
    scene = MagicMock(); scene.objects = [sun]
    scene.world = None
    apply_sky_preset(scene, "golden-hour")
    assert sun.data.energy == 50.0  # golden-hour energy after exposure-tuning fix
    assert tuple(sun.data.color) == (1.0, 0.78, 0.55)
    assert scene.view_settings.exposure == 1.0  # golden-hour exposure after tuning


def test_apply_sky_preset_warns_on_missing_sun(capsys):
    from blender_tools.sky_presets import apply_sky_preset
    scene = MagicMock(); scene.objects = []; scene.world = None
    apply_sky_preset(scene, "noon")
    cap = capsys.readouterr()
    assert "no Sun light" in cap.out


@pytest.mark.parametrize("preset", ["noon", "golden-hour", "blue-hour",
                                     "dawn", "overcast", "afternoon"])
def test_each_preset_is_apply_able(preset):
    from blender_tools.sky_presets import apply_sky_preset
    sun = MagicMock(); sun.type = "LIGHT"; sun.data = MagicMock(); sun.data.type = "SUN"
    scene = MagicMock(); scene.objects = [sun]; scene.world = None
    apply_sky_preset(scene, preset)  # must not raise
