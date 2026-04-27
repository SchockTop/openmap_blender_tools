"""Unit tests for features.groundcover — MagicMock-based since bpy is Blender-only."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


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
                        lambda b, t, c, cu, density=5.0: fake_mod)
    # Make the curve mock yield a sensible arc length for _density_for_target.
    bp0 = MagicMock(); bp0.co = MagicMock(); bp0.co.x = 0; bp0.co.y = 0; bp0.co.z = 0
    bp1 = MagicMock(); bp1.co = MagicMock(); bp1.co.x = 100; bp1.co.y = 0; bp1.co.z = 0
    spline = MagicMock(); spline.bezier_points = [bp0, bp1]; spline.points = []
    fake_curve.data.splines = [spline]
    out = groundcover.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["groundcover_modifier_name"] == "GroundcoverScatter"
    assert out["groundcover_template_count"] == 3
    assert out["groundcover_curve_name"] == "FlightPath"
    assert "groundcover_density" in out


def test_density_for_target_scales_with_arc():
    """Larger curves should get smaller per-m² density to keep total bounded."""
    groundcover = _import_feature()

    def mk_curve(arc_length):
        bp0 = MagicMock(); bp0.co = MagicMock(); bp0.co.x = 0; bp0.co.y = 0; bp0.co.z = 0
        bp1 = MagicMock(); bp1.co = MagicMock(); bp1.co.x = arc_length; bp1.co.y = 0; bp1.co.z = 0
        spline = MagicMock(); spline.bezier_points = [bp0, bp1]; spline.points = []
        curve = MagicMock(); curve.data.splines = [spline]
        return curve

    # 100m curve, 50000 target, 200m vicinity → density = 50000/(100*2*200) = 1.25
    d_short = groundcover._density_for_target(mk_curve(100), target_count=50000, vicinity_m=200)
    # 4000m curve same target → density = 50000/(4000*2*200) = 0.03125
    d_long = groundcover._density_for_target(mk_curve(4000), target_count=50000, vicinity_m=200)
    assert d_short > d_long
    assert d_short == pytest.approx(1.25, rel=0.01)
    assert d_long == pytest.approx(0.03125, rel=0.01)


def test_density_for_target_caps_at_5():
    groundcover = _import_feature()
    spline = MagicMock(); spline.bezier_points = []; spline.points = []
    curve = MagicMock(); curve.data.splines = [spline]
    # Arc 0 -> use floor density 1.0.
    assert groundcover._density_for_target(curve, 50000, 200) == 1.0
