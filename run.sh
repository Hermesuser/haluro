#!/usr/bin/env bash
# Native macOS launcher for Haluro — Laboratorio Analógico Digital
set -euo pipefail
cd "$(dirname "$0")"

if command -v /opt/anaconda3/bin/python3 >/dev/null 2>&1 && [[ -z "${VIRTUAL_ENV:-}" ]]; then
  PYTHON_BIN="/opt/anaconda3/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ "${1:-}" == "--web" ]]; then
  shift
  exec "${PYTHON_BIN}" start.py "$@"
else
  exec "${PYTHON_BIN}" native_app.py "$@"
fi
