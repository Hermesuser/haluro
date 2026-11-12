# Guía de Notarización de macOS para Haluro

Este documento explica cómo eliminar la advertencia de Gatekeeper ("desarrollador no verificado") de Haluro en macOS.

## Resumen del problema

Haluro está compilado con PyInstaller pero **no está firmado con un certificado de Apple Developer**. Por eso Gatekeeper lo bloquea al ejecutarlo.

## Requisitos previos

1. **Cuenta de Apple Developer** (USD 99/año): https://developer.apple.com
2. **macOS** con Xcode instalado (para `codesign`, `notarytool`, `stapler`)
3. **Acceso al repositorio de GitHub** para configurar secretos CI

## Paso 1 — Crear certificado de firma de código

1. Inicia sesión en https://developer.apple.com
2. Ve a **Certificates, Identifiers & Profiles** > **Certificates** > **+**
3. Selecciona **Developer ID Application** (no "Mac App Distribution")
4. Sigue el asistente para crear una CSR (Certificate Signing Request) en tu Mac
5. Descarga el certificado `.cer` y instálalo en tu llavero
6. Exporta el certificado como `.p12` (incluye la clave privada)

## Paso 2 — Obtener credenciales de notarización

1. Ve a https://appleid.apple.com/account/manage
2. Genera una **contraseña específica de la app** para "notarytool"
3. Anota tu **Team ID** (en la sección de membresía)

## Paso 3 — Configurar secretos en GitHub

En tu repositorio de GitHub, ve a **Settings > Secrets and variables > Actions** y añade:

| Secreto | Valor | Descripción |
|---------|-------|-------------|
| `MACOS_CERTIFICATE` | `base64` del `.p12` | Certificado de firma codificado en base64 |
| `MACOS_CERT_PASSWORD` | `texto` | Contraseña del `.p12` |
| `APPLE_ID` | `correo@ejemplo.com` | Tu Apple ID de desarrollador |
| `APPLE_APP_SPECIFIC_PASSWORD` | `xxxx-xxxx-xxxx-xxxx` | Contraseña específica para notarytool |
| `APPLE_TEAM_ID` | `ABCD123456` | Tu Team ID de Apple Developer |
| `MACOS_IDENTITY` | `Developer ID Application: Tu Nombre (TEAMID)` | Identidad de firma |

## Paso 4 — Generar el `.p12` en base64 para el secreto

```bash
# En tu Mac local
base64 -i tu_certificado.p12 | pbcopy
# Pega el resultado en el secreto MACOS_CERTIFICATE de GitHub
```

## Paso 5 — Ejecutar el release

1. Crea un tag en Git: `git tag v2.5.0 && git push origin v2.5.0`
2. GitHub Actions ejecutará automáticamente:
   - **Code signing**: Firma el `.app` y el `.dmg` con tu certificado
   - **Notarización**: Envía los archivos a Apple para verificación
   - **Stapling**: Adjunta el ticket de notarización al `.app` y `.dmg`

## Paso 6 — Verificar la notarización

Después del release, descarga el DMG y verifica:

```bash
# Verificar que el .app está firmado
codesign -dv --verbose=4 /Applications/Haluro.app

# Verificar que está notarizado
spctl --assess --type execute /Applications/Haluro.app
# Debería mostrar: /Applications/Haluro.app: accepted
```

## Paso 7 — Distribución

Una vez notarizado, los usuarios podrán abrir Haluro sin advertencias de Gatekeeper. El `.app` y el `.dmg` llevarán el ticket de notarización de Apple.

## Archivos relevantes en el repositorio

| Archivo | Descripción |
|---------|-------------|
| `.github/workflows/release.yml` | Pipeline de CI con pasos de signing y notarización |
| `packaging/macos/Entitlements.plist` | Entitlements del bundle (red, archivos, etc.) |
| `haluro.spec` | Especificación de PyInstaller para macOS |
| `packaging/macos/build_macos.sh` | Script de compilación local de macOS |

## Soporte

Si tienes problemas con la notarización, consulta:
- https://developer.apple.com/documentation/security/notarizing_your_app_before_distribution
- https://developer.apple.com/documentation/security/code-signing-your-app
