"""CLI-stub smoke test — confirms argparse multiplexer dispatches."""

from __future__ import annotations

import pytest

from blender_tools import cli


def test_cli_stubs_exit_with_code_2(capsys):
    """Stub subcommands print a 'not yet implemented' message and exit 2.

    Excludes subcommands in cli._IMPLEMENTED which have real parsers/handlers.
    """
    stub_commands = [cmd for cmd in cli._SUBCOMMANDS if cmd not in cli._IMPLEMENTED]
    for cmd in stub_commands:
        with pytest.raises(SystemExit) as exc:
            cli.main([cmd])
        assert exc.value.code == 2, f"Expected exit 2 for stub '{cmd}'"
        captured = capsys.readouterr()
        assert "not yet implemented" in captured.err, f"Expected stub message for '{cmd}'"
        assert cmd in captured.err, f"Expected command name in stub message for '{cmd}'"


def test_cli_unknown_command_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["no-such-command"])
    # argparse exits with 2 for unknown choices
    assert exc.value.code == 2


def test_subcommand_help_survives_cp1252_stdout(monkeypatch):
    """Regression: --help on subcommands with non-ASCII help text must not
    crash on Windows where stdout defaults to cp1252.

    Simulates the Windows default by redirecting stdout/stderr through a
    cp1252-encoded stream. main() must reconfigure to utf-8 (or otherwise
    tolerate non-ASCII) before argparse writes help.
    """
    import io
    import sys

    cp = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp)
    monkeypatch.setattr(sys, "stderr", cp)

    # geo-import help contains U+2192 ("→") — the original failure case.
    for cmd in ("geo-import", "terrain-setup", "ndvi-scatter", "world-setup"):
        with pytest.raises(SystemExit) as exc:
            cli.main([cmd, "--help"])
        assert exc.value.code == 0, f"{cmd} --help should exit 0"


def test_full_pipeline_operator_class_exists():
    from blender_tools import operators
    cls = getattr(operators, "BLENDERTOOLS_OT_full_pipeline", None)
    assert cls is not None, "Operator class missing"
    assert cls.bl_idname == "blender_tools.full_pipeline"
    # Must accept a region and engine.
    annot = getattr(cls, "__annotations__", {})
    assert "region" in annot or hasattr(cls, "region")
    assert "engine" in annot or hasattr(cls, "engine")


def test_full_pipeline_panel_exists():
    from blender_tools import operators
    panel = getattr(operators, "BLENDERTOOLS_PT_panel", None)
    assert panel is not None
    assert panel.bl_space_type == "VIEW_3D"
    assert panel.bl_region_type == "UI"
