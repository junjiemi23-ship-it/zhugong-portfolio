#!/bin/bash
# One-shot: create a virtualenv + install deps for the bridge and its tests.
# Portable: resolves paths relative to this script, no machine-specific absolutes.
# Prefers `uv` when available (fast), falls back to stdlib venv + pip.
set -e

# Resolve the bridge dir = wherever this script lives (works on Git-Bash / Linux / macOS).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PY_VER="${BRIDGE_PY_VER:-3.12}"
VENV=".venv"

# Pick a python interpreter for bootstrapping the venv.
if command -v python >/dev/null 2>&1; then PY=python
elif command -v python3 >/dev/null 2>&1; then PY=python3
else echo "ERROR: no python/python3 on PATH"; exit 1; fi

# venv interpreter path differs on Windows (Scripts) vs POSIX (bin).
if [ -f "$VENV/Scripts/python.exe" ]; then VPY="$VENV/Scripts/python.exe"
else VPY="$VENV/bin/python"; fi

DEPS="fastapi uvicorn httpx pytest"

if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV" --python "$PY_VER" -q
  uv pip install --python "$VPY" -q $DEPS
else
  "$PY" -m venv "$VENV"
  "$VPY" -m pip install -q --upgrade pip
  "$VPY" -m pip install -q $DEPS
fi

"$VPY" -c "import fastapi, httpx, pytest; print('DEPS_OK')"
