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
_IMPLEMENTED = {"geo-import", "terrain-setup", "citygml-import", "ndvi-scatter", "waypoints-to-camera", "world-setup"}


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


def _build_terrain_setup_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the terrain-setup subcommand parser."""
    p = subparsers.add_parser(
        "terrain-setup",
        help="Build Blender terrain from EXR heightmap (must run inside Blender).",
    )
    p.add_argument(
        "--heightmap",
        required=True,
        metavar="PATH",
        help="Path to the 32-bit float EXR heightmap.",
    )
    p.add_argument(
        "--size",
        nargs=2,
        type=float,
        required=True,
        metavar=("X", "Y"),
        help="Terrain size in metres (X Y).",
    )
    p.add_argument(
        "--subdivisions",
        type=int,
        default=11,
        metavar="N",
        help="Subsurf Simple subdivision level [0–14]. Default: 11.",
    )
    p.add_argument(
        "--anchor",
        nargs=3,
        type=float,
        default=[0.0, 0.0, 0.0],
        metavar=("X", "Y", "Z"),
        help="UTM32N anchor (easting northing altitude) subtracted from world coords. "
             "Default: 0 0 0.",
    )
    p.add_argument(
        "--strength",
        type=float,
        default=1.0,
        metavar="F",
        help="Displace modifier strength (metres per unit). Default: 1.0.",
    )
    p.add_argument(
        "--blend-out",
        dest="blend_out",
        metavar="PATH",
        default=None,
        help="If given, save the resulting .blend file to this path.",
    )


def _run_terrain_setup(args: argparse.Namespace) -> int:
    """Dispatch the terrain-setup subcommand.

    If bpy is already in sys.modules (i.e. we are running inside Blender),
    call build_terrain_from_heightmap directly.  Otherwise, print a helpful
    message explaining how to invoke via blender --background.
    """
    if "bpy" not in sys.modules:
        print(
            "[blender-tools] terrain-setup requires Blender's bundled Python.\n"
            "Run it as:\n"
            "  blender --background --factory-startup --python -c \"\n"
            "  import sys; sys.path.insert(0, '<repo>/research_bot')\n"
            "  from blender_tools.terrain_setup import build_terrain_from_heightmap\n"
            "  build_terrain_from_heightmap(\n"
            f"      heightmap_exr='{args.heightmap}',\n"
            f"      size_meters=({args.size[0]}, {args.size[1]}),\n"
            f"      subdivisions={args.subdivisions},\n"
            f"      anchor_utm32n=({args.anchor[0]}, {args.anchor[1]}, {args.anchor[2]}),\n"
            f"      strength={args.strength},\n"
            "  )\n"
            + (
                f"  import bpy; bpy.ops.wm.save_as_mainfile(filepath='{args.blend_out}')\n"
                if args.blend_out else ""
            )
            + "  \"",
            file=sys.stderr,
        )
        return 2

    # Running inside Blender — dispatch directly.
    from blender_tools.terrain_setup import build_terrain_from_heightmap
    import bpy  # type: ignore[import-not-found]

    obj = build_terrain_from_heightmap(
        heightmap_exr=args.heightmap,
        size_meters=(args.size[0], args.size[1]),
        subdivisions=args.subdivisions,
        strength=args.strength,
        anchor_utm32n=(args.anchor[0], args.anchor[1], args.anchor[2]),
    )
    print(f"[blender-tools] Terrain object '{obj.name}' created.")

    if args.blend_out:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.blend_out).resolve()))
        print(f"[blender-tools] Saved .blend to: {args.blend_out}")

    return 0


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


def _build_citygml_import_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the citygml-import subcommand parser."""
    p = subparsers.add_parser(
        "citygml-import",
        help="Convert LoD2 CityGML to CityJSON via citygml-tools.",
    )
    p.add_argument(
        "--input",
        dest="input",
        nargs="+",
        required=True,
        metavar="GML",
        help="One or more input CityGML (.gml) file paths.",
    )
    p.add_argument(
        "--output",
        dest="output",
        required=True,
        metavar="JSON",
        help="Destination CityJSON output file path.",
    )
    p.add_argument(
        "--docker",
        dest="docker",
        action="store_true",
        default=False,
        help="Use Docker fallback (citygml4j/citygml-tools image) instead of local CLI.",
    )


def _run_citygml_import(args: argparse.Namespace) -> int:
    """Dispatch the citygml-import subcommand."""
    from blender_tools.citygml_import import gml_to_cityjson

    input_gmls = [Path(p) for p in args.input]
    output_json = Path(args.output)
    result = gml_to_cityjson(input_gmls, output_json, use_docker=args.docker)
    print(f"[blender-tools] CityJSON written to: {result}")
    return 0


def _build_ndvi_scatter_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the ndvi-scatter subcommand parser."""
    p = subparsers.add_parser(
        "ndvi-scatter",
        help="Compute NDVI or generate Geometry-Nodes density config from NDVI raster.",
    )
    p.add_argument(
        "--mode",
        choices=["compute", "config"],
        required=True,
        help="'compute': run gdal_calc.py to produce NDVI GeoTIFF. "
             "'config': print GN density config JSON for an existing NDVI GeoTIFF.",
    )
    # compute-mode args
    p.add_argument(
        "--red",
        dest="red",
        metavar="PATH",
        help="[compute mode] Red-band GeoTIFF path.",
    )
    p.add_argument(
        "--nir",
        dest="nir",
        metavar="PATH",
        help="[compute mode] NIR-band GeoTIFF path.",
    )
    p.add_argument(
        "--output",
        dest="output",
        metavar="PATH",
        help="[compute mode] Output NDVI GeoTIFF path.",
    )
    # config-mode args
    p.add_argument(
        "--ndvi",
        dest="ndvi",
        metavar="PATH",
        help="[config mode] Path to the NDVI GeoTIFF.",
    )
    p.add_argument(
        "--threshold-low",
        dest="threshold_low",
        type=float,
        default=0.2,
        metavar="F",
        help="[config mode] Lower NDVI threshold (density=0 below this). Default: 0.2.",
    )
    p.add_argument(
        "--threshold-high",
        dest="threshold_high",
        type=float,
        default=0.8,
        metavar="F",
        help="[config mode] Upper NDVI threshold (density=max above this). Default: 0.8.",
    )
    p.add_argument(
        "--max-density",
        dest="max_density",
        type=float,
        default=0.5,
        metavar="F",
        help="[config mode] Max scatter density in points/m². Default: 0.5.",
    )
    p.add_argument(
        "--distribution",
        dest="distribution",
        choices=["POISSON", "RANDOM"],
        default="POISSON",
        help="[config mode] Distribute-Points-on-Faces method. Default: POISSON.",
    )


def _run_ndvi_scatter(args: argparse.Namespace) -> int:
    """Dispatch the ndvi-scatter subcommand."""
    import json as _json

    if args.mode == "compute":
        if not args.red or not args.nir or not args.output:
            print(
                "[blender-tools] ndvi-scatter --mode compute requires --red, --nir, --output",
                file=sys.stderr,
            )
            return 1
        from blender_tools.ndvi_scatter import compute_ndvi

        result = compute_ndvi(Path(args.red), Path(args.nir), Path(args.output))
        print(f"[blender-tools] NDVI GeoTIFF written to: {result}")
        return 0

    # config mode
    if not args.ndvi:
        print(
            "[blender-tools] ndvi-scatter --mode config requires --ndvi",
            file=sys.stderr,
        )
        return 1
    from blender_tools.ndvi_scatter import ndvi_to_density_config

    cfg = ndvi_to_density_config(
        ndvi_tif=Path(args.ndvi),
        threshold_low=args.threshold_low,
        threshold_high=args.threshold_high,
        max_density_per_m2=args.max_density,
        distribution_method=args.distribution,
    )
    print(_json.dumps(cfg, indent=2))
    return 0


def _build_waypoints_to_camera_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the waypoints-to-camera subcommand parser."""
    p = subparsers.add_parser(
        "waypoints-to-camera",
        help="Build Bezier camera path from WGS84 waypoint CSV (must run inside Blender).",
    )
    p.add_argument(
        "--csv",
        dest="csv",
        required=True,
        metavar="PATH",
        help="Path to the WGS84 waypoints CSV (columns: lat, lon, alt).",
    )
    p.add_argument(
        "--anchor",
        nargs=3,
        type=float,
        default=[0.0, 0.0, 0.0],
        metavar=("X", "Y", "Z"),
        help="UTM32N anchor (easting northing altitude) subtracted from world coords. "
             "Default: 0 0 0.",
    )
    p.add_argument(
        "--speed",
        dest="speed",
        type=float,
        default=50.0,
        metavar="F",
        help="Camera travel speed in m/s. Default: 50.0.",
    )
    p.add_argument(
        "--fps",
        dest="fps",
        type=int,
        default=25,
        metavar="N",
        help="Scene frame rate. Default: 25.",
    )


def _run_waypoints_to_camera(args: argparse.Namespace) -> int:
    """Dispatch the waypoints-to-camera subcommand.

    If not running under bpy, print a helpful message explaining how to invoke
    via blender --background. Otherwise, call wgs84_csv_to_bezier directly.
    """
    if "bpy" not in sys.modules:
        print(
            "[blender-tools] waypoints-to-camera requires Blender's bundled Python.\n"
            "Run it as:\n"
            "  blender --background --factory-startup --python -c \"\n"
            "  import sys; sys.path.insert(0, '<repo>/research_bot')\n"
            "  from blender_tools.waypoints_to_camera import wgs84_csv_to_bezier\n"
            "  wgs84_csv_to_bezier(\n"
            f"      csv_path='{args.csv}',\n"
            f"      anchor_utm32n=({args.anchor[0]}, {args.anchor[1]}, {args.anchor[2]}),\n"
            f"      speed_mps={args.speed},\n"
            f"      fps={args.fps},\n"
            "  )\n"
            "  \"",
            file=sys.stderr,
        )
        return 1

    # Running inside Blender — dispatch directly.
    from blender_tools.waypoints_to_camera import wgs84_csv_to_bezier

    curve_obj = wgs84_csv_to_bezier(
        csv_path=args.csv,
        anchor_utm32n=(args.anchor[0], args.anchor[1], args.anchor[2]),
        speed_mps=args.speed,
        fps=args.fps,
    )
    print(f"[blender-tools] Bezier curve '{curve_obj.name}' created.")
    return 0


def _build_world_setup_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the world-setup subcommand parser."""
    p = subparsers.add_parser(
        "world-setup",
        help="Configure sky + atmosphere + clouds (must run inside Blender).",
    )
    p.add_argument(
        "--preset",
        choices=["airbus-clean", "client-default", "spacex-warm"],
        default="client-default",
        help="Named aesthetic preset. Default: client-default.",
    )
    p.add_argument(
        "--bbox",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        default=None,
        help="Flight-path bounding box in metres (X Y Z) for the domain-cube haze volume.",
    )


def _run_world_setup(args: argparse.Namespace) -> int:
    """Dispatch the world-setup subcommand.

    If not running under bpy, print a helpful message explaining how to invoke
    via blender --background. Otherwise, call the world_setup functions directly.
    """
    if "bpy" not in sys.modules:
        print(
            "[blender-tools] world-setup must run inside Blender; "
            "invoke via `blender --background --python -c '...'`.",
            file=sys.stderr,
        )
        return 2

    # Running inside Blender — dispatch directly.
    from blender_tools.world_setup import setup_multiple_scattering_sky, add_domain_cube_volume

    world = setup_multiple_scattering_sky(preset=args.preset)
    print(f"[blender-tools] World '{world.name}' configured with preset '{args.preset}'.")

    if args.bbox is not None:
        cube = add_domain_cube_volume(
            bbox_meters=(args.bbox[0], args.bbox[1], args.bbox[2]),
            preset=args.preset,
        )
        print(f"[blender-tools] Domain-cube haze object '{cube.name}' added.")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blender-tools",
        description="Blender 5.x pipeline tools for IR-Unity-Research.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")
    subparsers.required = True

    # Register implemented commands with real parsers.
    _build_geo_import_parser(subparsers)
    _build_terrain_setup_parser(subparsers)
    _build_citygml_import_parser(subparsers)
    _build_ndvi_scatter_parser(subparsers)
    _build_waypoints_to_camera_parser(subparsers)
    _build_world_setup_parser(subparsers)

    # Register the remaining stub commands as minimal parsers so argparse
    # accepts them before we print the stub message.
    _STUB_COMMANDS = [cmd for cmd in _SUBCOMMANDS if cmd not in _IMPLEMENTED]
    for cmd in _STUB_COMMANDS:
        subparsers.add_parser(cmd, help=f"[stub] {cmd} — not yet implemented.")

    args, _unknown = parser.parse_known_args(argv)

    if args.command == "geo-import":
        # Re-parse strictly with only the geo-import subparser to get proper errors.
        return _run_geo_import(args)

    if args.command == "terrain-setup":
        return _run_terrain_setup(args)

    if args.command == "citygml-import":
        return _run_citygml_import(args)

    if args.command == "ndvi-scatter":
        return _run_ndvi_scatter(args)

    if args.command == "waypoints-to-camera":
        return _run_waypoints_to_camera(args)

    if args.command == "world-setup":
        return _run_world_setup(args)

    # All other commands are stubs.
    _stub(args.command)
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
