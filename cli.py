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
from pathlib import Path

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

# Subcommands with real implementations (not stubs).
_IMPLEMENTED = {"geo-import"}


def _stub(name: str) -> None:
    print(
        f"[blender-tools] '{name}' is scaffolded but not yet implemented. "
        f"Tracked by Phase 2 W6 plan.",
        file=sys.stderr,
    )
    sys.exit(2)


def _build_geo_import_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the geo-import subcommand parser."""
    p = subparsers.add_parser(
        "geo-import",
        help="Preprocess DGM/DOP GeoTIFFs into EXR heightmap or UDIM tiles.",
    )
    p.add_argument(
        "--input",
        dest="input",
        nargs="+",
        required=True,
        metavar="TIF",
        help="One or more input GeoTIFF paths.",
    )
    p.add_argument(
        "--mode",
        choices=["heightmap", "udim"],
        default="heightmap",
        help="Output mode: 'heightmap' (DGM→EXR) or 'udim' (DOP→UDIM tiles). "
             "Default: heightmap.",
    )
    # Heightmap-mode options
    p.add_argument(
        "--output-exr",
        dest="output_exr",
        metavar="PATH",
        help="[heightmap mode] Destination EXR file path.",
    )
    # UDIM-mode options
    p.add_argument(
        "--output-dir",
        dest="output_dir",
        metavar="DIR",
        help="[udim mode] Directory where UDIM tile JPEGs will be written.",
    )
    p.add_argument(
        "--tile-grid",
        dest="tile_grid",
        nargs=2,
        type=int,
        metavar=("U", "V"),
        default=[10, 4],
        help="[udim mode] Grid dimensions as U V (columns rows). Default: 10 4.",
    )
    # Shared optional
    p.add_argument(
        "--bbox",
        dest="bbox",
        nargs=4,
        type=float,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        default=None,
        help="Crop bbox in EPSG:25832 (UTM32N): xmin ymin xmax ymax.",
    )


def _run_geo_import(args: argparse.Namespace) -> int:
    """Dispatch the geo-import subcommand to the real implementation."""
    from blender_tools.geo_import import dgm_tif_to_exr_heightmap, dop_to_udim_tiles

    input_tifs = [Path(p) for p in args.input]
    bbox = tuple(args.bbox) if args.bbox is not None else None  # type: ignore[arg-type]

    if args.mode == "heightmap":
        if not args.output_exr:
            print(
                "[blender-tools] geo-import --mode heightmap requires --output-exr",
                file=sys.stderr,
            )
            return 1
        output_exr = dgm_tif_to_exr_heightmap(
            input_tifs=input_tifs,
            output_exr=Path(args.output_exr),
            bbox_utm32n=bbox,
        )
        print(f"[blender-tools] EXR heightmap written to: {output_exr}")
        return 0

    # udim mode
    if not args.output_dir:
        print(
            "[blender-tools] geo-import --mode udim requires --output-dir",
            file=sys.stderr,
        )
        return 1
    if bbox is None:
        print(
            "[blender-tools] geo-import --mode udim requires --bbox",
            file=sys.stderr,
        )
        return 1
    tile_paths = dop_to_udim_tiles(
        input_orthos=input_tifs,
        bbox_utm32n=bbox,  # type: ignore[arg-type]
        output_dir=Path(args.output_dir),
        tile_grid=(args.tile_grid[0], args.tile_grid[1]),
    )
    print(f"[blender-tools] {len(tile_paths)} UDIM tile(s) written to: {args.output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blender-tools",
        description="Blender 5.x pipeline tools for IR-Unity-Research.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    subparsers.required = True

    # Register geo-import with a real parser.
    _build_geo_import_parser(subparsers)

    # Register the remaining 8 commands as minimal stub parsers so argparse
    # accepts them before we print the stub message.
    _STUB_COMMANDS = [cmd for cmd in _SUBCOMMANDS if cmd not in _IMPLEMENTED]
    for cmd in _STUB_COMMANDS:
        subparsers.add_parser(cmd, help=f"[stub] {cmd} — not yet implemented.")

    args, _unknown = parser.parse_known_args(argv)

    if args.command == "geo-import":
        # Re-parse strictly with only the geo-import subparser to get proper errors.
        return _run_geo_import(args)

    # All other commands are stubs.
    _stub(args.command)
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
