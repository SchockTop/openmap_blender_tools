"""Tests for the feature registry (plain CPython, no bpy needed)."""
from __future__ import annotations
import sys
import textwrap
from pathlib import Path

import pytest


def _make_temp_pkg(tmp_path: Path, modules: dict[str, str]) -> Path:
    """Create a temp package 'fakefeats' with __init__.py + given module files."""
    pkg = tmp_path / "fakefeats"
    pkg.mkdir()
    # The __init__.py must be a copy of the real registry so we test its discover().
    real_init = Path(__file__).resolve().parent.parent / "features" / "__init__.py"
    (pkg / "__init__.py").write_text(real_init.read_text(encoding="utf-8"),
                                     encoding="utf-8")
    for name, body in modules.items():
        (pkg / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return pkg


def test_discover_returns_modules_with_NAME_and_apply(tmp_path, monkeypatch, capsys):
    """Discovery picks up modules that expose NAME + apply, skips others."""
    _make_temp_pkg(tmp_path, {
        "good": (
            "NAME = 'good-feature'\n"
            "DESCRIPTION = 'x'\n"
            "def apply(ctx):\n"
            "    return {'k': 1}\n"
        ),
        "bad": (
            "NAME = 'bad-feature'\n"
            "# no apply()\n"
        ),
        "broken": "import nonexistent_module_xyz\n",
    })
    monkeypatch.syspath_prepend(str(tmp_path))
    # Drop any cached import.
    for k in list(sys.modules):
        if k.startswith("fakefeats"):
            del sys.modules[k]
    import fakefeats  # type: ignore

    found = fakefeats.discover()
    assert "good-feature" in found
    assert "bad-feature" not in found  # missing apply
    # broken.py raises on import - skipped silently with warning
    err = capsys.readouterr().err
    assert "broken" in err


def test_apply_enabled_no_op_on_empty_list(tmp_path, monkeypatch):
    """Empty enabled list = no-op, returns context unchanged."""
    _make_temp_pkg(tmp_path, {})
    monkeypatch.syspath_prepend(str(tmp_path))
    for k in list(sys.modules):
        if k.startswith("fakefeats"):
            del sys.modules[k]
    import fakefeats  # type: ignore

    ctx = {"x": 1}
    out = fakefeats.apply_enabled([], ctx)
    assert out == {"x": 1}


def test_apply_enabled_warns_on_unknown_feature(tmp_path, monkeypatch, capsys):
    """Unknown feature name = warned, skipped."""
    _make_temp_pkg(tmp_path, {})
    monkeypatch.syspath_prepend(str(tmp_path))
    for k in list(sys.modules):
        if k.startswith("fakefeats"):
            del sys.modules[k]
    import fakefeats  # type: ignore

    out = fakefeats.apply_enabled(["does-not-exist"], {"x": 1})
    captured = capsys.readouterr()
    assert "not available" in captured.err
    assert out == {"x": 1}


def test_apply_enabled_continues_past_failures(tmp_path, monkeypatch, capsys):
    """One failing feature must not stop the others."""
    _make_temp_pkg(tmp_path, {
        "boom": (
            "NAME = 'boom'\n"
            "DESCRIPTION = 'raises'\n"
            "def apply(ctx):\n"
            "    raise RuntimeError('kaboom')\n"
        ),
        "ok": (
            "NAME = 'ok'\n"
            "DESCRIPTION = 'ok'\n"
            "def apply(ctx):\n"
            "    return {'ran_ok': True}\n"
        ),
    })
    monkeypatch.syspath_prepend(str(tmp_path))
    for k in list(sys.modules):
        if k.startswith("fakefeats"):
            del sys.modules[k]
    import fakefeats  # type: ignore

    ctx = {"x": 1}
    out = fakefeats.apply_enabled(["boom", "ok"], ctx)
    err = capsys.readouterr().err
    assert "FAIL boom" in err
    assert out["ran_ok"] is True
    assert out["x"] == 1


def test_apply_enabled_merges_outputs_into_context(tmp_path, monkeypatch):
    """Later features see earlier features' outputs in the context."""
    _make_temp_pkg(tmp_path, {
        "first": (
            "NAME = 'first'\n"
            "DESCRIPTION = 'f'\n"
            "def apply(ctx):\n"
            "    return {'first_ran': 42}\n"
        ),
        "second": (
            "NAME = 'second'\n"
            "DESCRIPTION = 's'\n"
            "def apply(ctx):\n"
            "    assert ctx.get('first_ran') == 42\n"
            "    return {'second_saw_first': True}\n"
        ),
    })
    monkeypatch.syspath_prepend(str(tmp_path))
    for k in list(sys.modules):
        if k.startswith("fakefeats"):
            del sys.modules[k]
    import fakefeats  # type: ignore

    out = fakefeats.apply_enabled(["first", "second"], {})
    assert out["first_ran"] == 42
    assert out["second_saw_first"] is True


def test_real_registry_imports_buildings_textured():
    """The real features package must expose buildings-textured."""
    # Drop cached imports first so we get a fresh look.
    for k in list(sys.modules):
        if k.startswith("blender_tools.features") or k == "blender_tools.features":
            del sys.modules[k]
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    # The package is loadable as `features` from openmap_blender_tools/features.
    feat_pkg_path = Path(__file__).resolve().parent.parent / "features"
    assert (feat_pkg_path / "__init__.py").exists()
    assert (feat_pkg_path / "buildings_textured.py").exists()
    # Import via path-aware sys.path trick.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if "features" in sys.modules:
        del sys.modules["features"]
    if "features.buildings_textured" in sys.modules:
        del sys.modules["features.buildings_textured"]
    import features  # type: ignore
    found = features.discover()
    assert "buildings-textured" in found


def test_import_dommesh_operator_registered():
    """BLENDERTOOLS_OT_import_dommesh must be in operators.CLASSES (AST check, no bpy)."""
    import ast

    ops_path = Path(__file__).resolve().parent.parent / "operators.py"
    tree = ast.parse(ops_path.read_text(encoding="utf-8"))

    # Collect all class definitions.
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert "BLENDERTOOLS_OT_import_dommesh" in class_names, (
        "BLENDERTOOLS_OT_import_dommesh class not found in operators.py"
    )

    # Confirm it appears in the CLASSES tuple assignment.
    classes_src = ops_path.read_text(encoding="utf-8")
    assert "BLENDERTOOLS_OT_import_dommesh" in classes_src.split("CLASSES = (")[1].split(")")[0], (
        "BLENDERTOOLS_OT_import_dommesh not listed in CLASSES tuple"
    )


def test_add_clouds_operator_registered():
    """BLENDERTOOLS_OT_add_clouds must be defined and listed in CLASSES (AST, no bpy)."""
    import ast

    ops_path = Path(__file__).resolve().parent.parent / "operators.py"
    src = ops_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert "BLENDERTOOLS_OT_add_clouds" in class_names, (
        "BLENDERTOOLS_OT_add_clouds class not found in operators.py"
    )

    classes_block = src.split("CLASSES = (")[1].split(")")[0]
    assert "BLENDERTOOLS_OT_add_clouds" in classes_block, (
        "BLENDERTOOLS_OT_add_clouds not listed in CLASSES tuple"
    )


def test_clouds_feature_has_NAME_and_apply():
    """features/clouds.py must expose NAME='clouds' and an apply() callable."""
    import sys
    from pathlib import Path as _Path

    feat_pkg_path = _Path(__file__).resolve().parent.parent / "features"
    assert (feat_pkg_path / "clouds.py").exists(), "features/clouds.py is missing"

    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    for k in list(sys.modules):
        if k.startswith("features"):
            del sys.modules[k]
    import features  # type: ignore

    found = features.discover()
    assert "clouds" in found, f"'clouds' not in discovered features; got: {list(found)}"
    assert callable(found["clouds"].apply), "clouds.apply must be callable"
