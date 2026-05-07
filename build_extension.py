"""Assemble a Blender 4.2+ extension zip for blender_tools.

Outputs  dist/blender_tools-<version>.zip  with:
    blender_manifest.toml
    __init__.py, cli.py, operators.py, <all runtime .py modules>
    wheels/*.whl                           (from vendor/, filtered by manifest)

The resulting zip installs via:
    blender --command extension install-file dist/blender_tools-<v>.zip \\
            --repo user_default --enable

Usage:
    python build_extension.py                    # writes dist/blender_tools-0.1.0.zip
    python build_extension.py --output path.zip

Runs in plain CPython (no bpy). Tested on Python 3.12.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # 3.10 fallback
    import tomli as tomllib  # type: ignore

HERE = Path(__file__).resolve().parent

RUNTIME_MODULES = [
    "__init__.py",
    "altitude_handler.py",
    "cli.py",
    "camera_presets.py",
    "cinematic_preset.py",
    "citygml_import.py",
    "cleanup_pymeshlab.py",
    "csv_curve_import.py",
    "dop_projector.py",
    "geo_import.py",
    "hidden_geo_cull.py",
    "ndvi_scatter.py",
    "operators.py",
    "quality_presets.py",
    "sky_presets.py",
    "step_retessellate.py",
    "terrain_setup.py",
    "waypoint_generators.py",
    "waypoints_to_camera.py",
    "world_setup.py",
]


def load_manifest() -> dict:
    with (HERE / "blender_manifest.toml").open("rb") as f:
        return tomllib.load(f)


def assemble(staging: Path, manifest: dict) -> None:
    # 1. Copy manifest.
    shutil.copy(HERE / "blender_manifest.toml", staging / "blender_manifest.toml")

    # 2. Copy runtime modules.
    for rel in RUNTIME_MODULES:
        src = HERE / rel
        if not src.exists():
            raise FileNotFoundError(f"Expected runtime module missing: {src}")
        shutil.copy(src, staging / rel)

    # 2b. Copy features/ subpackage as a directory tree.
    features_src = HERE / "features"
    if features_src.is_dir():
        shutil.copytree(features_src, staging / "features",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # 2c. Copy assets/ (trees.blend and leaf textures) as a directory tree.
    assets_src = HERE / "assets"
    if assets_src.is_dir():
        shutil.copytree(assets_src, staging / "assets",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                      "*.blend1"))

    # 2d. Copy vendored GDAL binaries (Windows 64-bit).
    gdal_src = HERE / "vendor" / "gdal-win64"
    if gdal_src.is_dir():
        shutil.copytree(gdal_src, staging / "vendor" / "gdal-win64",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # 3. Copy wheels declared in manifest.
    wheels_dir = staging / "wheels"
    wheels_dir.mkdir()
    vendor = HERE / "vendor"
    missing = []
    for wheel_ref in manifest.get("wheels", []):
        # Manifest paths are "./wheels/<name>.whl"; we resolve to vendor/<name>.
        name = Path(wheel_ref).name
        src = vendor / name
        if not src.exists():
            missing.append(str(src))
            continue
        shutil.copy(src, wheels_dir / name)
    if missing:
        raise FileNotFoundError(
            "Wheels declared in manifest but missing from vendor/:\n  - "
            + "\n  - ".join(missing)
        )


def zip_dir(src_dir: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output zip path (default: dist/blender_tools-<version>.zip)",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest()
    version = manifest["version"]
    out_zip = args.output or (HERE / "dist" / f"blender_tools-{version}.zip")

    with tempfile.TemporaryDirectory(prefix="blender_tools_build_") as tmp:
        staging = Path(tmp) / "blender_tools"
        staging.mkdir()
        assemble(staging, manifest)
        zip_dir(staging, out_zip)

    size_kb = out_zip.stat().st_size / 1024
    print(f"Built: {out_zip}  ({size_kb:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
