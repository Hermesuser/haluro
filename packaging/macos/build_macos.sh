#!/usr/bin/env bash
# =============================================================================
# Haluro v2.4.1 — Reproducible macOS Native App & DMG Build Pipeline
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VERSION="2.4.1"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  : # Use user-specified PYTHON_BIN
elif [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
elif command -v /opt/anaconda3/bin/python3 >/dev/null 2>&1 && [[ -z "${VIRTUAL_ENV:-}" ]]; then
  PYTHON_BIN="/opt/anaconda3/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

ARCH="$("${PYTHON_BIN}" -c "import platform; print(platform.machine())")"

echo "==> [1/4] Ejecutando suite de pruebas automatizadas (pytest) con ${PYTHON_BIN} ..."
"${PYTHON_BIN}" -m pytest -v

echo "==> [2/4] Verificando arranque de motor y puente nativo (--smoke-test) ..."
"${PYTHON_BIN}" native_app.py --smoke-test

mkdir -p dist

if "${PYTHON_BIN}" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "==> [3/4] Compilando bundle autónomo Haluro.app con PyInstaller ..."
  rm -rf build dist/Haluro dist/Haluro.app
  "${PYTHON_BIN}" -m PyInstaller --noconfirm --clean haluro.spec
  APP_BUNDLE="dist/Haluro.app"
else
  echo "==> [3/4] PyInstaller no instalado en este entorno; verificando Haluro.app nativo local ..."
  APP_BUNDLE="Haluro.app"
fi

# Evitar que FileProvider/Finder en ~/Documents contamine atributos extendidos al firmar
STAGE_DIR="/tmp/haluro_packaging_$$"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"
cp -R "${APP_BUNDLE}" "${STAGE_DIR}/Haluro.app"

dot_clean "${STAGE_DIR}/Haluro.app" 2>/dev/null || true
xattr -cr "${STAGE_DIR}/Haluro.app"
codesign --force --deep -s - "${STAGE_DIR}/Haluro.app"
codesign --verify --deep --strict "${STAGE_DIR}/Haluro.app"

DMG_PATH="dist/Haluro-${VERSION}-macOS-${ARCH}.dmg"
echo "==> [4/4] Empaquetando imagen de disco ${DMG_PATH} ..."
rm -f "${DMG_PATH}"
hdiutil create \
  -volname "Haluro ${VERSION} (${ARCH})" \
  -srcfolder "${STAGE_DIR}/Haluro.app" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

rm -rf "${STAGE_DIR}"

(cd dist && shasum -a 256 Haluro-*.dmg > "SHA256SUMS-macOS.txt")
echo "Construcción macOS completada: ${DMG_PATH}"
