"""Unit tests for features.trees — MagicMock-based since bpy is Blender-only."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _import_feature():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    for k in list(sys.modules):
        if k in {"features", "features.trees"}:
            del sys.modules[k]
    import features.trees as trees  # type: ignore
    return trees


def test_trees_module_has_required_attributes():
    trees = _import_feature()
    assert trees.NAME == "trees"
    assert isinstance(trees.DESCRIPTION, str)
    assert callable(trees.apply)


def test_apply_skips_when_no_terrain_and_no_fallback(monkeypatch, capsys):
    trees = _import_feature()
    # Force the fallback to also yield nothing -> apply must skip cleanly.
    monkeypatch.setattr(trees, "_find_or_create_fallback_terrain",
                        lambda bpy: None)
    ctx = {"bpy": MagicMock(), "terrain_obj": None}
    out = trees.apply(ctx)
    assert out == {}
    cap = capsys.readouterr()
    assert "no terrain" in cap.out.lower()


def test_apply_publishes_template_count_and_mod_name(monkeypatch):
    trees = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()
    terrain.modifiers.get.return_value = None
    fake_mod = MagicMock()
    fake_mod.name = "TreeScatter"
    terrain.modifiers.new.return_value = fake_mod
    coll = MagicMock()
    coll.objects = [MagicMock(), MagicMock(), MagicMock()]
    fake_bpy.data.collections.__contains__.return_value = False
    fake_bpy.data.collections.new.return_value = coll
    monkeypatch.setattr(trees, "_ensure_tree_templates", lambda b: coll)
    monkeypatch.setattr(trees, "_attach_or_replace_gn_scatter",
                        lambda b, t, c: fake_mod)
    out = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["trees_template_count"] == 3
    assert out["trees_modifier_name"] == "TreeScatter"
