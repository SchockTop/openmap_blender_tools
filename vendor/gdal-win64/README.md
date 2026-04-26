# Vendored GDAL — Win64 (offline build)

GDAL **3.12.3 "Chicoutimi"** (released 2026/03/17), extracted from the
**conda-forge `gdal` Win64 package**. License: **MIT/X11** (see
https://github.com/OSGeo/gdal/blob/master/LICENSE.TXT).

## Contents

```
bin/    50 binaries — gdal_translate.exe, gdalbuildvrt.exe, gdalinfo.exe
        + transitive DLL closure (gdal.dll, proj_9.dll, geos.dll, libtiff.dll, …)
share/proj/    PROJ datum-grid database (proj.db) — required for EPSG:25832 ↔ WGS84
share/gdal/    GDAL CSV resource files
```

## Why vendored

`research_bot/blender_tools/geo_import.py` calls `gdal_translate` /
`gdalbuildvrt` via `subprocess`. Vendoring keeps the project usable **offline
and without admin install** (no OSGeo4W / no conda env required).

## How to refresh

```bash
# In a writable scratch dir:
conda create -p ./gdal_env -c conda-forge gdal -y

# Compute transitive DLL closure for the binaries we ship:
cd ./gdal_env/Library/bin
{
  declare -A seen; queue=(gdal_translate.exe gdalbuildvrt.exe gdalinfo.exe gdal.dll)
  while [ ${#queue[@]} -gt 0 ]; do
    cur="${queue[0]}"; queue=("${queue[@]:1}")
    [ -n "${seen[$cur]:-}" ] && continue; seen[$cur]=1
    [ ! -f "$cur" ] && continue
    while IFS= read -r dll; do
      base=$(basename "$dll"); [ -z "${seen[$base]:-}" ] && queue+=("$base")
    done < <(ldd "$cur" 2>/dev/null | grep -F "/gdal_env/" | awk '{print $1}')
  done
  for f in "${!seen[@]}"; do echo "$f"; done | sort > /tmp/closure.txt
}

# Copy:
mkdir -p .../vendor/gdal-win64/{bin,share}
while read f; do cp "$f" .../vendor/gdal-win64/bin/; done < /tmp/closure.txt
cp -r ../share/proj  .../vendor/gdal-win64/share/proj
cp -r ../share/gdal  .../vendor/gdal-win64/share/gdal
```

The discovery / env-overlay logic lives in `geo_import._vendored_gdal_env` and
`_resolve_gdal_bin`.
