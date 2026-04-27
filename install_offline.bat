@echo off
REM Offline install for blender_tools — no network, no proxy, no certs.
REM Run from this directory (research_bot\blender_tools) in cmd.exe.
REM
REM Usage:
REM     install_offline.bat           (uses "python" on PATH)
REM     install_offline.bat C:\Python312\python.exe  (explicit interpreter)

setlocal

set PY=%~1
if "%PY%"=="" set PY=python

echo Using Python: %PY%
%PY% --version || (echo Python not found. Pass full path as first arg. & exit /b 1)

echo.
echo [1/3] Installing build backend (setuptools + wheel) from vendor\ ...
REM Required because step 3 uses --no-build-isolation; pip needs setuptools
REM importable in the target Python to read pyproject.toml's build-system.
%PY% -m pip install --no-index --find-links "%~dp0vendor" setuptools wheel || exit /b 1

echo.
echo [2/3] Installing runtime deps from vendor\ (no network)...
%PY% -m pip install --no-index --find-links "%~dp0vendor" pyproj numpy trimesh certifi || exit /b 1

echo.
echo [3/3] Installing blender_tools in editable mode (no deps, no build isolation)...
%PY% -m pip install --no-deps --no-build-isolation -e "%~dp0." || exit /b 1

echo.
echo Done. Verify with:
echo     %PY% -c "from blender_tools import cli; cli.main(['--help'])"
endlocal
