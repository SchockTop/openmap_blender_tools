"""tests/test_quality_presets.py"""
from unittest.mock import MagicMock
import pytest

from blender_tools import quality_presets


def _fake_scene():
    s = MagicMock()
    s.render.resolution_x = 0
    s.render.resolution_y = 0
    s.render.use_simplify = False
    s.render.simplify_subdivision = 0
    s.render.simplify_subdivision_render = 0
    s.eevee.taa_render_samples = 0
    s.cycles.samples = 0
    return s


def test_all_three_presets_registered():
    assert set(quality_presets.QUALITY_PRESETS.keys()) == {"draft", "preview", "final"}


@pytest.mark.parametrize("name", ["draft", "preview", "final"])
def test_each_preset_has_required_keys(name):
    p = quality_presets.QUALITY_PRESETS[name]
    for key in ("resolution", "eevee_taa_render_samples", "cycles_samples",
                "viewport_simplify_subdiv", "render_simplify_subdiv",
                "skip_features"):
        assert key in p, f"preset {name!r} missing key {key!r}"
    assert isinstance(p["resolution"], tuple) and len(p["resolution"]) == 2


def test_get_preset_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        quality_presets.get_preset("ultra")


def test_apply_quality_unknown_raises_keyerror():
    scene = _fake_scene()
    with pytest.raises(KeyError):
        quality_presets.apply_quality(scene, "bogus")


def test_apply_quality_draft_sets_low_resolution_and_samples():
    scene = _fake_scene()
    quality_presets.apply_quality(scene, "draft")
    assert scene.render.resolution_x == 480
    assert scene.render.resolution_y == 270
    assert scene.eevee.taa_render_samples == 8
    assert scene.cycles.samples == 16
    assert scene.render.use_simplify is True
    assert scene.render.simplify_subdivision == 3
    assert scene.render.simplify_subdivision_render == 5


def test_apply_quality_final_sets_full_hd_and_high_samples():
    scene = _fake_scene()
    quality_presets.apply_quality(scene, "final")
    assert scene.render.resolution_x == 1920
    assert scene.render.resolution_y == 1080
    assert scene.eevee.taa_render_samples == 128
    assert scene.cycles.samples == 256
    assert scene.render.simplify_subdivision_render == 11


def test_apply_quality_preview_midline_values():
    scene = _fake_scene()
    quality_presets.apply_quality(scene, "preview")
    assert (scene.render.resolution_x, scene.render.resolution_y) == (960, 540)
    assert scene.eevee.taa_render_samples == 32
    assert scene.cycles.samples == 64


def test_skip_features_only_set_for_draft():
    assert quality_presets.QUALITY_PRESETS["draft"]["skip_features"] == ["groundcover"]
    assert quality_presets.QUALITY_PRESETS["preview"]["skip_features"] == []
    assert quality_presets.QUALITY_PRESETS["final"]["skip_features"] == []


def test_apply_quality_returns_preset_dict():
    scene = _fake_scene()
    result = quality_presets.apply_quality(scene, "preview")
    assert result is quality_presets.QUALITY_PRESETS["preview"]
