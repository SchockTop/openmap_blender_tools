#!/usr/bin/env bash
# Offline install for blender_tools — no network, no proxy, no certs.
# Run from this directory (research_bot/blender_tools) in bash/git-bash.
#
# Usage:
#     ./install_offline.sh                    # uses "python" on PATH
#     ./install_offline.sh /c/Python312/python.exe
set -euo pipefail

PY="${1:-python}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Using Python: $PY"
"$PY" --version

echo
echo "[1/3] Installing build backend (setuptools + wheel) from vendor/ ..."
# Required because step 3 uses --no-build-isolation; pip needs setuptools
# importable in the target Python to read pyproject.toml's build-system.
"$PY" -m pip install --no-index --find-links "$HERE/vendor" setuptools wheel

echo
echo "[2/3] Installing runtime deps from vendor/ (no network)..."
"$PY" -m pip install --no-index --find-links "$HERE/vendor" pyproj numpy trimesh certifi

echo
echo "[3/3] Installing blender_tools in editable mode (no deps, no build isolation)..."
"$PY" -m pip install --no-deps --no-build-isolation -e "$HERE"

echo
echo "Done. Verify with:"
echo "    $PY -c \"from blender_tools import cli; cli.main(['--help'])\""
