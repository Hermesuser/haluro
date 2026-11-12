#!/bin/bash
# =============================================================================
# Haluro — Script de Instalación para macOS (Apple Silicon / Intel)
# =============================================================================
# Uso:
#   1. Descarga Haluro-2.5.0-macOS-arm64.dmg (o .x86_64.dmg)
#   2. Haz doble clic en el DMG para montarlo
#   3. Arrastra Haluro.app a la carpeta Aplicaciones
#   4. Ejecuta este script: ./install_haluro.command
#
# O ejecuta directamente con la ruta del DMG:
#   ./install_haluro.command /ruta/al/Haluro-2.5.0-macOS-arm64.dmg
# =============================================================================

set -euo pipefail

APP_NAME="Haluro"
APP_BUNDLE="${APP_NAME}.app"
APPLICATIONS_DIR="/Applications"
DMG_PATH="${1:-}"

echo "============================================================"
echo "  Haluro — Instalador para macOS"
echo "============================================================"
echo ""

# Detectar arquitectura
ARCH=$(uname -m)
echo "🔍 Arquitectura detectada: ${ARCH}"
if [[ "${ARCH}" == "arm64" ]]; then
    echo "   → Apple Silicon (M1/M2/M3/M4)"
else
    echo "   → Intel x86_64"
fi
echo ""

# Si se proporcionó un DMG, montarlo y copiar la app
if [[ -n "${DMG_PATH}" && -f "${DMG_PATH}" ]]; then
    echo "📦 Montando imagen de disco: ${DMG_PATH}"
    hdiutil attach "${DMG_PATH}" -nobrowse -quiet 2>&1 || {
        echo "❌ Error: No se pudo montar el DMG."
        exit 1
    }

    # Buscar el .app en los volúmenes montados
    APP_SOURCE=""
    for vol in /Volumes/*/; do
        if [[ -d "${vol}${APP_BUNDLE}" ]]; then
            APP_SOURCE="${vol}${APP_BUNDLE}"
            break
        fi
    done

    if [[ -z "${APP_SOURCE}" ]]; then
        echo "❌ Error: No se encontró ${APP_BUNDLE} dentro del DMG."
        hdiutil detach "$(hdiutil attach | grep "${DMG_PATH}" | awk '{print $1}')" -quiet 2>&1 || true
        exit 1
    fi

    echo "📋 Copiando ${APP_BUNDLE} a ${APPLICATIONS_DIR}..."
    rm -rf "${APPLICATIONS_DIR}/${APP_BUNDLE}"
    cp -R "${APP_SOURCE}" "${APPLICATIONS_DIR}/${APP_BUNDLE}"

    echo "💾 Desmontando DMG..."
    hdiutil detach "$(df | grep "${APP_SOURCE}" | awk '{print $1}')" -quiet 2>&1 || true
else
    echo "ℹ️  No se proporcionó DMG. Asumiendo que ${APP_BUNDLE} ya está en ${APPLICATIONS_DIR}."
fi

# Verificar que la app existe
if [[ ! -d "${APPLICATIONS_DIR}/${APP_BUNDLE}" ]]; then
    echo "❌ Error: ${APP_BUNDLE} no se encuentra en ${APPLICATIONS_DIR}"
    echo "   Asegúrate de haber arrastrado la app a Aplicaciones primero."
    exit 1
fi

echo ""
echo "🔐 Limpiando atributos de cuarentena y extended attributes..."

# Eliminar atributo de cuarentena (com.apple.quarantine)
xattr -d com.apple.quarantine "${APPLICATIONS_DIR}/${APP_BUNDLE}" 2>/dev/null || true
xattr -cr "${APPLICATIONS_DIR}/${APP_BUNDLE}" 2>/dev/null || true

# Hacer ejecutable el binario principal
chmod +x "${APPLICATIONS_DIR}/${APP_BUNDLE}/Contents/MacOS/Haluro" 2>/dev/null || true

echo "✅ Atributos limpiados."

echo ""
echo "🚀 Iniciando Haluro..."
open -n "${APPLICATIONS_DIR}/${APP_BUNDLE}" 2>&1 || {
    echo ""
    echo "⚠️  Si macOS muestra una advertencia de 'desarrollador no verificado':"
    echo "   1. Ve a Preferencias del Sistema > Privacidad y Seguridad > Seguridad"
    echo "   2. Busca el mensaje sobre Haluro y haz clic en 'Abrir de todas formas'"
    echo ""
    echo "   O ejecuta en Terminal para bypass temporal de Gatekeeper:"
    echo "   sudo spctl --master-disable"
    exit 1
}

echo ""
echo "============================================================"
echo "  ✅ Haluro instalado y ejecutándose correctamente."
echo "============================================================"
