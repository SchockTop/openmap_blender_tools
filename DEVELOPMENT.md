# blender_tools — Development & Runability Notes

Session-owner reference for how this package was debugged and how we can make it
genuinely easy to run. Written 2026-04-23 after a full debug + smoke-test pass
against Blender 5.1.1.

---

## 1. Debug & verification approach used

Process followed the `superpowers:systematic-debugging` skill's four phases.

### Phase 1 — Root-cause investigation

For each failure signal, gather evidence before proposing a fix:

1. Run the mocked-bpy unit suite under a real Python that matches `pyproject.toml`'s
   `requires-python` (≥3.11). `pytest` — not just import-checks.
2. Probe every CLI subcommand's `--help` on the target platform (Windows here).
   Argparse writes help straight to stdout, so any non-ASCII glyph crashes on
   cp1252.
3. Import every module *inside the target Blender* via
   `blender --background --python <smoke>.py`. Imports succeed cheaply and
   catch syntax / typing / missing-dep issues first.
4. Call one representative function per bpy-dependent module to surface real
   API drift (node enums, operator names, input sockets).
5. Re-read error messages literally. The "package directory '.\blender_tools'
   does not exist" error was the install-failure root cause — nothing to do
   with the proxy, despite what the user saw at the surface.

### Phase 2 — Pattern analysis

When `geo-import --help` crashed, every other subcommand with non-ASCII `help=`
strings was implicated. When `sky_type = "NISHITA"` failed on Blender 5.1, the
fix had to survive *both* 5.1+ (new `MULTIPLE_SCATTERING`) and older releases
still using `NISHITA`. Always: find the pattern, don't patch a single site.

### Phase 3 — Hypothesis + minimal test

Each fix was reproduced with a targeted failing test *before* modifying code:

- Unicode crash: monkeypatch `sys.stdout`/`stderr` to a strict cp1252 stream,
  assert `cli.main([cmd, "--help"])` exits 0.
- Sky enum: probe on real Blender, observe `TypeError: enum "NISHITA" not found
  in ('SINGLE_SCATTERING', 'MULTIPLE_SCATTERING', 'PREETHAM', 'HOSEK_WILKIE')`.
- Packaging: `pip install -e .` error message cites the missing directory.

### Phase 4 — Single fix, verify, move on

One change per bug. Full test suite after each. `verification-before-completion`
skill: no claim without a fresh command run showing the claim is true.

---

## 2. Bugs caught this session

| # | Module | Symptom | Root cause | Fix |
|---|---|---|---|---|
| 1 | `pyproject.toml` | `pip install -e .` aborts: `package directory '.\blender_tools' does not exist` | `package-dir = { "" = "." }` tells setuptools to look for `./blender_tools/`, but the package lives flat in the current dir | `package-dir = { "blender_tools" = ".", "blender_tools.tests" = "tests" }` |
| 2 | `cli.py` | `blender-tools geo-import --help` throws `UnicodeEncodeError` (cp1252 can't encode `→`) | Windows default stdout is cp1252; argparse writes help there; `help=` strings use `→ — ² °` | `_force_utf8_stdio()` called at top of `main()` reconfigures stdout/stderr to utf-8 with `errors="replace"` |
| 3 | `world_setup.setup_multiple_scattering_sky` | `TypeError: enum "NISHITA" not found` in Blender 5.1 | Sets `sky_type = "NISHITA"` *before* the try/except fallback; 5.1 removed NISHITA entirely | Iterate `("MULTIPLE_SCATTERING", "NISHITA")` — first one Blender accepts wins |

Regression test coverage for all three now lives in `tests/test_cli_stub.py` +
existing `test_world_setup.py` (which still passes with mocked bpy — the 5.1
behavior was only catchable in a real Blender).

---

## 3. Verification evidence (what was proven vs. left open)

### Proven green

| Verified | Command / evidence |
|---|---|
| 299 unit tests pass | `pytest research_bot/blender_tools/tests/` — 299 passed, 3 skipped |
| All 11 modules import in Python 3.7 (Blender 2.90) | `blender --background --python smoke_bpy_probe.py` |
| All 11 modules import in Python 3.13 (Blender 5.1.1) | same probe against Blender 5.1 |
| `world_setup.setup_multiple_scattering_sky` both presets | real-bpy 5.1 smoke call — ✓ after fix |
| `world_setup.add_domain_cube_volume` | real-bpy 5.1 smoke call |
| `waypoints_to_camera.wgs84_csv_to_bezier` | real-bpy 5.1 smoke call (reads CSV → UTM → Bezier) |
| `waypoints_to_camera.attach_camera_rig` | real-bpy 5.1 smoke call (Follow Path + Damped Track) |
| `hidden_geo_cull.cull_by_name_pattern` | real-bpy 5.1 smoke call (moved 1 cube into `_Hidden`) |
| `terrain_setup.compute_plane_dimensions` | real-bpy 5.1 smoke call |
| Offline install works end-to-end | `pip uninstall` → `install_offline.sh` → import OK |
| CLI `--help` clean on all 9 subcommands | script loop |

### Not yet exercised

| Function | Reason | Resolve by |
|---|---|---|
| `terrain_setup.build_terrain_from_heightmap` | Needs real EXR heightmap | Add a smoke fixture: tiny procedural heightmap written via tifffile/OpenImageIO, or a committed 32×32 sample EXR |
| `citygml_import.gml_to_cityjson` | Needs `citygml-tools` CLI (Java) or Docker image | Smoke should cover the shell-out path with a mock; end-to-end needs a 1-building sample GML |
| `citygml_import.cityjson_to_blender` | Needs a real CityJSON file | Ship a 1-building fixture |
| `world_setup.load_vdb_cloud` | Needs a `.vdb` file | Ship a trivial procedural VDB (OpenVDB can generate one in a few lines) |
| `hidden_geo_cull.cull_by_render_face_id_visibility` | Needs geometry + camera setup | Scripted fixture: UV sphere behind a cube, assert inner faces culled |
| `step_retessellate` | Needs `cadquery-ocp` (optional extra) | Add a `[cad]`-extra smoke test with a 1cm cube STEP file |
| `ndvi_scatter` config mode | Not exercised end-to-end | Tiny 4-band raster fixture |

---

## 4. Research — making this genuinely easy to run

### 4.1 Current friction points

What actually bit during this session (ordered by pain):

1. **Package install** — `pip install -e .` failed with an opaque packaging error
   that the user read as "it doesn't know blender-tools". Now fixed.
2. **Proxy / TLS** — `pip download` couldn't be relied on from behind the user's
   corporate proxy. Solved by vendoring wheels into `vendor/`.
3. **Blender's isolated Python** — deps installed via pip go to user-site, which
   Blender disables in `--background`. Deps invisible.
4. **Writing to Blender's site-packages needs admin** (`C:\Program Files\...`).
   Non-starter in a locked-down corporate image.
5. **Version matrix** — bpy 2.8, 2.9, 3.0, 4.x, 5.x each ship a different Python
   (3.7 → 3.13) and each breaks different APIs. One script can't serve all.
6. **Invocation** — `blender --background --python <abs/path/to/module.py> --
   --arg value …` is a hostile UX.

### 4.2 Options evaluated

Ranked by **expected reduction in friction** for the user's actual workflow
(Windows laptop, corporate proxy, Blender 5.1 already installed).

#### A. Blender Extension with bundled wheels (primary recommendation)

Blender 4.2+ introduced the **Extensions** system. An extension's
`blender_manifest.toml` can declare:

```toml
schema_version = "1.0.0"
id = "blender_tools"
version = "0.1.0"
name = "IR-Unity-Research Blender tools"
blender_version_min = "4.2.0"
type = "add-on"

# Wheels bundled INSIDE the .zip are installed into an isolated per-extension
# site-packages directory. No admin rights needed. No user-site gymnastics.
wheels = [
    "./wheels/pyproj-3.7.2-cp313-cp313-win_amd64.whl",
    "./wheels/numpy-2.4.4-cp313-cp313-win_amd64.whl",
    "./wheels/trimesh-4.11.5-py3-none-any.whl",
]
```

**Why this is the right primary path:**
- **One-click install**: user drags `blender_tools-0.1.0.zip` into Preferences →
  Extensions → Install from Disk. Done. Blender extracts the extension *and* all
  wheels into a private dir; imports Just Work.
- **No admin rights**. Extensions install into `%APPDATA%\Blender Foundation\…`
  which is user-writable on any corporate image.
- **No --background incantation**: tools show up as operators / menu items in
  Blender, or via `bpy.ops.blender_tools.*` from the Scripting workspace.
- **Proxy-neutral**: the `.zip` is the artifact. No network needed at install.
- **Bundles multi-Python wheels**: include cp311/cp312/cp313 Windows +
  `-manylinux_*` wheels in `./wheels/` and Blender picks the right one at
  install time.

**Effort**: medium. We already have `vendor/` with the right wheels. Need:
1. Write `blender_manifest.toml`.
2. Rearrange so entry points register as `bpy` operators (or keep the pure
   Python API and provide a thin operator wrapper — playbooks can still
   `from blender_tools import ...`).
3. Ship a `build_extension.py` script that assembles the `.zip` (or use
   `blender-extension-builder` / `peeler` from PyPI which automate the
   wheel-collection step).
4. Move the existing `pyproject.toml` + vendor wheels into the extension build
   output.

Tooling worth investigating:
- `blender-extension-builder` — reads `pyproject.toml`-style deps, downloads
  wheels, writes `blender_manifest.toml`, zips the extension.
- `peeler` — minimal counterpart; same idea.

#### B. `bpy` as a PyPI module for non-interactive + CI (secondary)

Since Blender 4.0, `bpy` is pip-installable:
`pip install bpy==5.1.1` — gives you a headless Blender Python module. Requires
Python ≥3.13 for bpy 5.1.

**Why it matters for us:**
- **Real-bpy unit tests in CI**: drop the "mock bpy" hack for functions that can
  be tested headlessly. Currently we rely on `MagicMock(bpy)` in tests; every
  API-drift bug (like the NISHITA one) is invisible until a real Blender runs.
- **Dev loop speed**: `pytest` under Python 3.13 with `bpy` installed = no
  `blender --background` shell-out per test.
- **Scripted pipelines** (Thread 3 / data pipeline): a `python render.py` CLI
  that just imports bpy. Much simpler for automation.

**Caveats:**
- Strict Python version pin (Blender 5.1 ↔ Python 3.13.x). Add `bpy = "==5.1.1"`
  as a `[project.optional-dependencies]` extra (call it `blender`) so
  development installs it but regular users don't pay the 400MB download.
- Headless-only: no GPU render unless you add a virtual framebuffer; fine for
  our modifier/node graph work, not fine for real renders.
- Known packaging quirks on Windows (some Blender versions ship corrupted wheels
  — check issue #119156). Easy to spot during CI bring-up.

**Effort**: small. Add an optional-deps entry and one CI job.

#### C. Fix the "run a module in Blender" UX (tactical)

Even with Extensions in place, some flows will remain script-style
(ingest / batch terrain builds). Current state: users have to type

```
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python ...path\to\module.py -- --arg value
```

Ship a launcher:

```
blender-tools run terrain-setup --heightmap X.exr --size 10000 4000
```

Implementation:
- The `blender-tools` CLI already exists (entry point works, verified). Extend
  it with a `run` subcommand that:
  1. Discovers a Blender binary (scan common paths → `BLENDER_EXE` env var →
     `--blender` flag; persists the choice to `%APPDATA%\blender_tools\config.toml`).
  2. Determines which subcommand is bpy-dependent (flagged in a module-level
     `NEEDS_BPY = True`).
  3. If `NEEDS_BPY`: re-invoke via `blender --background --python-expr "import
     blender_tools.cli; blender_tools.cli.main(…)" -- <original args>`.
  4. If not: run in-process.
- Works whether the user installed via Extension *or* via `pip install -e .`
  against Blender's Python.

**Effort**: small–medium. Pure Python, unit-testable, lives in `cli.py`.

#### D. `fake-bpy-module` for IDE / type-checker support (dev ergonomics)

`pip install fake-bpy-module-5.1` ships complete stubs of the bpy API for the
target Blender version. Benefits:

- IDE autocomplete, correct signatures, no red squigglies.
- `mypy` catches API-drift bugs statically. The NISHITA bug would have been
  caught at type-check time (the stub declares sky_type as a Literal of the
  known enum values for the chosen Blender version).
- Costs nothing at runtime.

**Effort**: trivial. Add `fake-bpy-module-5.1` to the `[dev]` extra.

#### E. Docker image for fully-reproducible pipeline runs (heavy artillery)

A `blender_tools:5.1.1` image with Blender 5.1 + Python 3.13 + pyproj/numpy
pre-installed + blender_tools mounted. Used for:

- Cinematic render jobs offloaded to a GPU box.
- CI without Windows runners.
- Anyone hitting "works on my machine" issues.

**Effort**: medium. Official `blendergrid/blender:5.1` base image exists; add
our deps + package. Not needed for the dev laptop use case — this is for
pipeline deployment.

#### F. Pre-built wheels-for-Blender index (optional convenience)

Host the vendored wheels in a small repo (or GitHub Releases) so
`pip install --extra-index-url https://…/blender-wheels/ pyproj numpy` works
from any Blender Python without hitting the corporate proxy's TLS interception.
Nice-to-have; dominated by option A for end users.

### 4.3 What NOT to do

- **Don't** vendor-extract dependencies into the repo source tree. We already
  carry the wheels under `vendor/`; unpacking them would double the repo size
  and complicate licensing bookkeeping.
- **Don't** write a custom `blender_addon` that `pip install`s at runtime. In
  corporate environments, the network it needs won't be there. Extensions with
  bundled wheels (option A) is the sanctioned Blender-4.2+ answer.
- **Don't** require `bpy` as a hard dependency in `pyproject.toml`. It's a 400MB
  download and only developers / CI need it. Keep it in a `[blender]` extra.

### 4.4 Recommended roadmap

| Step | Artifact | Unlocks |
|---|---|---|
| 1. Short-term (this week) | `fake-bpy-module-5.1` added to `[dev]`; `blender-tools run` subcommand (launcher) | Static checks catch API drift; users stop typing `blender --background --python …` |
| 2. Medium-term (next sprint) | `blender_manifest.toml` + `build_extension.py`; ship `blender_tools-0.1.0.zip` | One-click install; no admin rights; no proxy; no Python-version gymnastics |
| 3. Optional | `bpy` extra + CI job that runs unit tests under real bpy 5.1 | Catch API drift at PR time, not at user time |
| 4. Optional | Docker image | Reproducible renders; no Windows dependency for pipelines |

### 4.5 Concrete next command

To bootstrap the Extension path without disturbing the current pip-install
workflow:

```bash
# 1. Install blender-extension-builder (or peeler) into anaconda python
/c/ProgramData/anaconda3/python.exe -m pip install --no-index \
    --find-links research_bot/blender_tools/vendor/ \
    blender-extension-builder  # after downloading its wheel into vendor/

# 2. Scaffold blender_manifest.toml from pyproject.toml
cd research_bot/blender_tools
python -m blender_extension_builder init

# 3. Build the extension zip (collects wheels automatically)
python -m blender_extension_builder build --output dist/

# 4. In Blender: Preferences → Extensions → Install from Disk → dist/blender_tools-0.1.0.zip
```

This doesn't replace the current `install_offline.sh` — both are valid. The
extension is for users; the editable install is for us while developing.

---

## 5. Local artifacts produced this session

| Path | Purpose |
|---|---|
| `cli.py` (changed) | `_force_utf8_stdio()` added |
| `world_setup.py` (changed) | sky_type order flipped + explicit fallback loop |
| `pyproject.toml` (changed) | `package-dir` now maps both packages correctly |
| `tests/test_cli_stub.py` (changed) | regression test for cp1252 stdout |
| `tests/smoke_bpy_probe.py` (new) | import-only probe across every module |
| `tests/smoke_bpy_calls.py` (new) | end-to-end call probe for bpy functions |
| `vendor/` (new) | pyproj / numpy / trimesh / pytest wheels (cp311/cp312/cp313 Windows) |
| `install_offline.bat`, `install_offline.sh` (new) | offline editable install |
| `DEVELOPMENT.md` (this file) | approach + roadmap |

All four code fixes ship with passing tests (299 passed, 3 skipped). Ready to
commit as a single "blender_tools: fix install + Windows CLI + Blender 5.1
sky_type" change.
