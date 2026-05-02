"""Unit tests for dop_projector — DOPProjector Empty creation."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if "dop_projector" in sys.modules:
        del sys.modules["dop_projector"]
    import dop_projector
    return dop_projector


def test_creates_empty_at_bbox_min_with_correct_scale():
    mod = _import_module()
    fake_bpy = MagicMock()
    created = MagicMock()
    created.name = "DOPProjector"
    fake_bpy.data.objects.__contains__.return_value = False
    fake_bpy.data.objects.new.return_value = created

    bbox = (1000.0, 2000.0, 1500.0, 2400.0)  # min_x, min_y, max_x, max_y
    out = mod.ensure_dop_projector(fake_bpy, bbox)

    assert out is created
    assert created.location == (1000.0, 2000.0, 0.0)
    assert created.scale == (500.0, 400.0, 1.0)


def test_idempotent_when_already_exists():
    mod = _import_module()
    fake_bpy = MagicMock()
    existing = MagicMock(); existing.name = "DOPProjector"
    fake_bpy.data.objects.__contains__.return_value = True
    fake_bpy.data.objects.__getitem__.return_value = existing

    out = mod.ensure_dop_projector(fake_bpy, (0, 0, 100, 100))
    assert out is existing
    fake_bpy.data.objects.new.assert_not_called()
