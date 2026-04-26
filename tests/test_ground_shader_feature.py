"""Unit tests for features.ground_shader — MagicMock-based since bpy is Blender-only."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_feature():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    for k in list(sys.modules):
        if k in {"features", "features.ground_shader"}:
            del sys.modules[k]
    import features.ground_shader as ground_shader  # type: ignore
    return ground_shader


def test_module_exposes_required_attributes():
    ground_shader = _import_feature()
    assert ground_shader.NAME == "ground-shader"
    assert isinstance(ground_shader.DESCRIPTION, str)
    assert callable(ground_shader.apply)


def test_apply_skips_when_no_terrain(capsys):
    ground_shader = _import_feature()
    ctx = {"bpy": MagicMock(), "terrain_obj": None}
    out = ground_shader.apply(ctx)
    assert out == {}
    cap = capsys.readouterr()
    assert "no terrain" in cap.out.lower()


def test_apply_attaches_material_and_publishes(monkeypatch):
    ground_shader = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()
    # MagicMock for materials so .clear/.append are tracked, but make it
    # behave falsy/empty so the existing-material check yields None.
    materials_mock = MagicMock()
    materials_mock.__bool__.return_value = False
    materials_mock.__len__.return_value = 0
    materials_mock.__getitem__ = lambda self, i: None
    terrain.data.materials = materials_mock
    fake_mat = MagicMock(); fake_mat.name = "GroundShader_Layered"
    monkeypatch.setattr(ground_shader, "_build_procedural_ground_material",
                        lambda bpy, base_image_material=None: fake_mat)
    out = ground_shader.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["ground_shader_material"] == "GroundShader_Layered"
    assert out["ground_shader_combined_with_drape"] is False
    terrain.data.materials.clear.assert_called_once()
    terrain.data.materials.append.assert_called_once_with(fake_mat)


def test_apply_detects_existing_drape_and_combines(monkeypatch):
    ground_shader = _import_feature()
    fake_bpy = MagicMock()
    drape_mat = MagicMock(); drape_mat.name = "OrthoDrape"
    terrain = MagicMock()
    materials_mock = MagicMock()
    materials_mock.__bool__.return_value = True
    materials_mock.__len__.return_value = 1
    materials_mock.__getitem__ = lambda self, i: drape_mat
    terrain.data.materials = materials_mock
    captured = {}
    def fake_build(bpy, base_image_material=None):
        captured["base"] = base_image_material
        m = MagicMock(); m.name = "GroundShader_Layered"
        return m
    monkeypatch.setattr(ground_shader, "_build_procedural_ground_material", fake_build)
    out = ground_shader.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert captured["base"] is drape_mat
    assert out["ground_shader_combined_with_drape"] is True
