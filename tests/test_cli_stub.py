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
