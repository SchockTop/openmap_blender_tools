"""CLI multiplexer for blender_tools.

Usage:
    blender-tools <command> [options]

Commands (not-yet-implemented subcommands print a friendly stub):
    geo-import          Preprocess DGM/DOP tifs into EXR heightmap + UDIM tiles.
    terrain-setup       Build Blender terrain from EXR heightmap (inside Blender).
    citygml-import      Import LoD2 CityGML buildings into Blender.
    ndvi-scatter        Compute NDVI + build density field config.
    waypoints-to-camera Build Bezier camera path from WGS84 CSV.
    world-setup         Configure sky + atmosphere + clouds.
    step-retessellate   Retessellate a STEP file into glTF.
    cleanup-pymeshlab   Run mesh hygiene chain on a glTF/OBJ.
    hidden-geo-cull     Cull hidden interior geometry from a .blend.

Each subcommand is implemented in its own module; this file only dispatches.
"""

from __future__ import annotations

import argparse
import sys

_SUBCOMMANDS = [
    "geo-import",
    "terrain-setup",
    "citygml-import",
    "ndvi-scatter",
    "waypoints-to-camera",
    "world-setup",
    "step-retessellate",
    "cleanup-pymeshlab",
    "hidden-geo-cull",
]


def _stub(name: str) -> None:
    print(
        f"[blender-tools] '{name}' is scaffolded but not yet implemented. "
        f"Tracked by Phase 2 W6 plan.",
        file=sys.stderr,
    )
    sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blender-tools",
        description="Blender 5.x pipeline tools for IR-Unity-Research.",
    )
    parser.add_argument(
        "command",
        choices=_SUBCOMMANDS,
        help="Subcommand to run.",
    )
    parser.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the subcommand.",
    )
    args = parser.parse_args(argv)

    # Each subcommand will get its own real implementation in later tasks.
    _stub(args.command)
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
