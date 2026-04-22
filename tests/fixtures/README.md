# Test Fixtures

This directory holds small synthetic data files used by the blender_tools test suite.

## Contents

Currently empty — fixtures are generated programmatically by tests as needed
(e.g. via `tmp_path` pytest fixtures or by the test itself using GDAL/numpy).

## When to add a static fixture here

- Tiny synthetic GeoTIFFs (< 10 KB, 10×10 px) for GDAL integration tests.
- Minimal CSV waypoint files for `waypoints_to_camera` tests.
- Minimal STEP files (cube or cylinder, < 50 KB) for `step_retessellate` tests.

Any fixture that requires GDAL to generate should be committed as a binary
artifact rather than regenerated on every CI run. Mark the corresponding test
`@pytest.mark.needs_gdal` so it is skipped in environments without GDAL.

## Naming convention

```
fixtures/
  dgm1_10x10.tif          # 10×10 px Float32 DGM1 tile, UTM32N
  dop20_10x10.tif         # 10×10 px RGB DOP20 tile, UTM32N
  waypoints_munich.csv    # 5-point WGS84 route near Munich
  cube.step               # Minimal STEP AP242 cube for retessellation tests
```
