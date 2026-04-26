"""Unit tests for features.groundcover — MagicMock-based since bpy is Blender-only."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_feature():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    for k in list(sys.modules):
        if k in {"features", "features.groundcover"}:
            del sys.modules[k]
    import features.groundcover as groundcover  # type: ignore
    return groundcover


def test_module_attributes():
    groundcover = _import_feature()
    assert groundcover.NAME == "groundcover"
    assert isinstance(groundcover.DESCRIPTION, str)
    assert callable(groundcover.apply)


def test_apply_skips_when_no_terrain(capsys):
    groundcover = _import_feature()
    fake_bpy = MagicMock()
    fake_bpy.data.objects = []
    out = groundcover.apply({"bpy": fake_bpy, "terrain_obj": None})
    assert out == {}
    cap = capsys.readouterr()
    assert "no terrain" in cap.out.lower()


def test_apply_publishes_modifier_name(monkeypatch):
    groundcover = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()
    terrain.type = "MESH"
    terrain.name = "TerrainPlane"
    coll = MagicMock()
    coll.objects = [MagicMock(), MagicMock(), MagicMock()]
    fake_mod = MagicMock()
    fake_mod.name = "GroundcoverScatter"
    fake_curve = MagicMock()
    fake_curve.type = "CURVE"
    fake_curve.name = "FlightPath"
    fake_bpy.data.objects = [terrain, fake_curve]
    monkeypatch.setattr(groundcover, "_ensure_groundcover_templates", lambda b: coll)
    monkeypatch.setattr(groundcover, "_attach_or_replace_groundcover_gn",
                        lambda b, t, c, cu: fake_mod)
    out = groundcover.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["groundcover_modifier_name"] == "GroundcoverScatter"
    assert out["groundcover_template_count"] == 3
    assert out["groundcover_curve_name"] == "FlightPath"
