"""CLI-stub smoke test — confirms argparse multiplexer dispatches."""

from __future__ import annotations

import pytest

from blender_tools import cli


def test_cli_stubs_exit_with_code_2(capsys):
    """Every registered subcommand prints a 'not yet implemented' stub."""
    for cmd in cli._SUBCOMMANDS:
        with pytest.raises(SystemExit) as exc:
            cli.main([cmd])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "not yet implemented" in captured.err
        assert cmd in captured.err


def test_cli_unknown_command_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["no-such-command"])
    # argparse exits with 2 for unknown choices
    assert exc.value.code == 2
