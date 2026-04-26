"""tests/test_cinematic_preset.py"""
from unittest.mock import MagicMock
import pytest


def _fake_scene():
    s = MagicMock()
    s.render.engine = "CYCLES"
    s.render.use_simplify = False
    s.render.simplify_subdivision = 0
    s.render.resolution_x = 1920
    s.render.resolution_y = 1080
    s.cycles.samples = 0
    s.cycles.use_denoising = False
    s.eevee.use_volumetric_shadows = False
    s.eevee.taa_render_samples = 0
    s.view_settings.view_transform = ""
    return s


def test_apply_cinematic_preset_eevee(monkeypatch):
    from blender_tools import cinematic_preset
    fake_bpy = MagicMock()
    fake_bpy.data.cameras = []
    monkeypatch.setattr(cinematic_preset, "_require_bpy", lambda: fake_bpy)
    scene = _fake_scene()
    cinematic_preset.apply_cinematic_preset(scene, render_engine="BLENDER_EEVEE_NEXT")
    assert scene.render.engine == "BLENDER_EEVEE_NEXT"
    assert scene.render.use_simplify is True
    assert scene.eevee.use_volumetric_shadows is True
    assert scene.eevee.taa_render_samples >= 32
    assert scene.view_settings.view_transform == "AgX"


def test_apply_cinematic_preset_cycles(monkeypatch):
    from blender_tools import cinematic_preset
    fake_bpy = MagicMock()
    monkeypatch.setattr(cinematic_preset, "_require_bpy", lambda: fake_bpy)
    scene = _fake_scene()
    cinematic_preset.apply_cinematic_preset(scene, render_engine="CYCLES")
    assert scene.render.engine == "CYCLES"
    assert scene.cycles.samples >= 64
    assert scene.cycles.use_denoising is True


def test_set_camera_clip_for_large_scene(monkeypatch):
    from blender_tools import cinematic_preset
    cam_data = MagicMock(); cam_data.clip_start = 0.1; cam_data.clip_end = 1000.0
    cinematic_preset.set_camera_clip_for_large_scene(cam_data)
    assert cam_data.clip_start == 1.0
    assert cam_data.clip_end == 100_000.0


def test_ensure_cinematic_sun_creates_sun_when_none(monkeypatch):
    from blender_tools import cinematic_preset
    fake_bpy = MagicMock()
    monkeypatch.setattr(cinematic_preset, "_require_bpy", lambda: fake_bpy)
    scene = MagicMock(); scene.objects = []
    light_data = MagicMock(); fake_bpy.data.lights.new.return_value = light_data
    light_obj = MagicMock(); fake_bpy.data.objects.new.return_value = light_obj
    result = cinematic_preset._ensure_cinematic_sun(scene)
    fake_bpy.data.lights.new.assert_called_once()
    fake_bpy.data.objects.new.assert_called_once()
    scene.collection.objects.link.assert_called_once_with(light_obj)
    assert (light_data.type == "SUN"
            or fake_bpy.data.lights.new.call_args.kwargs.get("type") == "SUN")
    assert result is light_obj


def test_ensure_cinematic_sun_idempotent(monkeypatch):
    from blender_tools import cinematic_preset
    fake_bpy = MagicMock()
    monkeypatch.setattr(cinematic_preset, "_require_bpy", lambda: fake_bpy)
    existing_sun = MagicMock(); existing_sun.type = "LIGHT"
    existing_sun.data = MagicMock(); existing_sun.data.type = "SUN"
    scene = MagicMock(); scene.objects = [existing_sun]
    result = cinematic_preset._ensure_cinematic_sun(scene)
    fake_bpy.data.lights.new.assert_not_called()
    fake_bpy.data.objects.new.assert_not_called()
    assert result is existing_sun
