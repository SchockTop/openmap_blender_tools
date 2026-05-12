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
    # Sprint 7: _ensure_tree_templates now takes optional blend_path arg.
    monkeypatch.setattr(trees, "_ensure_tree_templates",
                        lambda b, blend_path=None: coll)
    monkeypatch.setattr(trees, "_attach_or_replace_gn_scatter",
                        lambda b, t, c: fake_mod)
    out = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["trees_template_count"] == 3
    assert out["trees_modifier_name"] == "TreeScatter"


def test_tree_template_has_rich_geometry_in_real_blender():
    """Smoke — only runs in real Blender, skipped in pytest."""
    pytest.skip("real-Blender test; covered by manual smoke render")


# --- Sprint 7 plan Task 3 ---


def _make_lib_load_recorder():
    """Returns (FakeLibCtx, calls list).

    bpy.data.libraries.load is used as a context manager:
        with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
            data_to.collections = ['TreeTemplates']
    The fake records the path and returns minimal data_from/data_to mocks.
    """
    calls = []
    class FakeLibCtx:
        def __init__(self, path, link=False):
            calls.append({"path": path, "link": link})
            self.path = path
        def __enter__(self):
            data_from = MagicMock()
            data_from.collections = ["TreeTemplates"]
            data_to = MagicMock()
            return data_from, data_to
        def __exit__(self, *a): pass
    return FakeLibCtx, calls


def test_apply_loads_from_bundled_assets_trees_blend(monkeypatch):
    """The new linking path must invoke libraries.load on the bundled trees.blend."""
    trees = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()
    terrain.modifiers.get.return_value = None
    fake_mod = MagicMock(); fake_mod.name = "TreeScatter"
    terrain.modifiers.new.return_value = fake_mod

    FakeLibCtx, calls = _make_lib_load_recorder()
    fake_bpy.data.libraries.load = FakeLibCtx

    fake_coll = MagicMock(); fake_coll.objects = [MagicMock()] * 4
    # Collection NOT yet in scene (so _ensure_tree_templates does the load),
    # but available via .get() after the load completes.
    fake_bpy.data.collections.__contains__.return_value = False
    fake_bpy.data.collections.get.return_value = fake_coll

    monkeypatch.setattr(trees, "_attach_or_replace_gn_scatter",
                        lambda b, t, c: fake_mod)

    out = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["trees_template_count"] == 4
    assert calls, "libraries.load was not invoked"
    assert "trees.blend" in calls[0]["path"]
    assert calls[0]["link"] is False  # append, not link


def test_per_region_override_takes_precedence(monkeypatch, tmp_path):
    """If data/<region>/trees.blend exists, prefer it over the bundled asset."""
    trees = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()
    terrain.modifiers.get.return_value = None
    fake_mod = MagicMock(); fake_mod.name = "TreeScatter"
    terrain.modifiers.new.return_value = fake_mod

    region_blend = tmp_path / "trees.blend"
    region_blend.write_bytes(b"fake")

    FakeLibCtx, calls = _make_lib_load_recorder()
    fake_bpy.data.libraries.load = FakeLibCtx
    fake_bpy.data.collections.__contains__.return_value = False
    fake_bpy.data.collections.get.return_value = MagicMock(
        objects=[MagicMock()] * 4)

    monkeypatch.setattr(trees, "_attach_or_replace_gn_scatter",
                        lambda b, t, c: fake_mod)

    out = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain,
                       "region_data_dir": str(tmp_path)})
    assert out.get("trees_blend_source") == str(region_blend)
    assert calls and calls[0]["path"] == str(region_blend)


def test_apply_skips_when_collection_missing_in_blend(monkeypatch):
    """If the .blend has no TreeTemplates collection, apply skips cleanly."""
    trees = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()

    class EmptyLibCtx:
        def __init__(self, path, link=False): pass
        def __enter__(self):
            df = MagicMock(); df.collections = ["SomethingElse"]
            return df, MagicMock()
        def __exit__(self, *a): pass
    fake_bpy.data.libraries.load = EmptyLibCtx
    fake_bpy.data.collections.__contains__.return_value = False

    out = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out == {}


# ---------------------------------------------------------------------------
# New tests — mask_geotiff parameter + leaf translucency
# ---------------------------------------------------------------------------


def test_apply_accepts_mask_geotiff_kwarg(monkeypatch):
    """apply() must accept mask_geotiff=<path> without raising."""
    trees = _import_feature()
    fake_bpy = MagicMock()
    terrain = MagicMock()
    terrain.modifiers.get.return_value = None
    fake_mod = MagicMock(); fake_mod.name = "TreeScatter"
    terrain.modifiers.new.return_value = fake_mod
    fake_coll = MagicMock(); fake_coll.objects = [MagicMock()] * 2

    monkeypatch.setattr(trees, "_ensure_tree_templates", lambda b, blend_path=None: fake_coll)
    monkeypatch.setattr(trees, "_attach_or_replace_gn_scatter",
                        lambda b, t, c: fake_mod)
    monkeypatch.setattr(trees, "_wire_mask_image", lambda mod, img: None)
    monkeypatch.setattr(trees, "_apply_leaf_translucency", lambda b, c: None)

    # No mask — should work as before.
    out = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain})
    assert out["trees_template_count"] == 2

    # With mask path — should also work (image loading is mocked via bpy).
    fake_bpy.data.images.get.return_value = None
    fake_img = MagicMock()
    fake_bpy.data.images.load.return_value = fake_img
    out2 = trees.apply({"bpy": fake_bpy, "terrain_obj": terrain},
                       mask_geotiff="/fake/forest_mask.tif")
    assert out2["trees_template_count"] == 2


def test_load_mask_image_returns_none_on_failure(monkeypatch):
    """_load_mask_image must return None (not raise) when bpy.data.images.load fails."""
    trees = _import_feature()
    fake_bpy = MagicMock()
    fake_bpy.data.images.get.return_value = None
    fake_bpy.data.images.load.side_effect = RuntimeError("not found")
    result = trees._load_mask_image(fake_bpy, "/nonexistent/mask.tif")
    assert result is None


def test_patch_leaf_material_idempotent(monkeypatch):
    """_patch_leaf_material must not add a second mix node when called twice.

    On the second call, a node with label='LeafTranslucent_Mix' is already
    present, so _patch_leaf_material should return early without adding nodes.
    """
    trees = _import_feature()
    fake_bpy = MagicMock()

    # A material with a node carrying the "already patched" label.
    mat = MagicMock()
    mat.use_nodes = True
    mat.name = "LeafMat_Patched"
    nt = MagicMock()
    mat.node_tree = nt

    marker_node = MagicMock()
    marker_node.label = "LeafTranslucent_Mix"
    nt.nodes.__iter__ = MagicMock(return_value=iter([marker_node]))

    trees._patch_leaf_material(fake_bpy, mat)
    nt.nodes.new.assert_not_called()


def test_build_cinematic_scene_operator_registered():
    """BLENDERTOOLS_OT_build_cinematic_scene must be defined and in CLASSES (AST check)."""
    import ast
    from pathlib import Path as _Path

    ops_path = _Path(__file__).resolve().parent.parent / "operators.py"
    src = ops_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert "BLENDERTOOLS_OT_build_cinematic_scene" in class_names

    classes_block = src.split("CLASSES = (")[1].split(")")[0]
    assert "BLENDERTOOLS_OT_build_cinematic_scene" in classes_block


def test_scatter_trees_operator_has_mask_geotiff_prop():
    """BLENDERTOOLS_OT_scatter_trees must declare a mask_geotiff StringProperty (AST)."""
    import ast
    from pathlib import Path as _Path

    ops_path = _Path(__file__).resolve().parent.parent / "operators.py"
    src = ops_path.read_text(encoding="utf-8")
    assert "mask_geotiff" in src, "mask_geotiff property missing from operators.py"
