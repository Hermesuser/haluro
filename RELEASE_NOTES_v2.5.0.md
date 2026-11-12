# Haluro v2.5.0 — Laboratorio Analógico Digital

## 📦 Instalación en macOS (Apple Silicon ARM64 y Intel)

### Opción A: Instalación rápida (recomendada)

1. Descarga `Haluro-2.5.0-macOS-arm64.dmg` (Apple Silicon) o `Haluro-2.5.0-macOS-x86_64.dmg` (Intel)
2. Haz doble clic en el DMG para montarlo
3. Arrastra `Haluro.app` a tu carpeta **Aplicaciones**
4. Ejecuta el script `install_haluro.command` incluido, o abre la app normalmente

### Opción B: Si Gatekeeper bloquea la app

macOS muestra: *"No se puede abrir Haluro porque no se puede verificar al desarrollador"*

**Solución:**
1. Ve a **Preferencias del Sistema > Privacidad y Seguridad > Seguridad**
2. Busca el mensaje sobre Haluro y haz clic en **"Abrir de todas formas"**
3. La app se abrirá y quedará autorizada para futuras ejecuciones

**O bypass temporal de Gatekeeper:**
```bash
sudo spctl --master-disable
# Abre la app normalmente, luego vuelve a activar:
sudo spctl --master-enable
```

## 🔐 Seguridad aplicada en v2.5.0

| Protección | Descripción |
|------------|-------------|
| Token de sesión persistente | No se regenera cada reinicio; persiste en `USER_DATA_ROOT/session.token` |
| Allow-list de exportación | Solo permite escribir en `DEVELOPED_DIR` y `~/Downloads` |
| Rate limiting | Cupos por endpoint para evitar DoS local (HTTP 429) |
| Cabeceras de seguridad | Permissions-Policy, COOP, COEP, CSP estricta |
| Checksums SHA-256 | Verificación de integridad de instaladores descargados |

## 🎨 Mejoras de UX

- **Persistencia de preferencias**: Película, modo, controles de simulación y negativo se guardan entre sesiones
- **Deshacer/Rehacer persistente**: Recetas por frame se guardan en `localStorage` y se restauran al reimportar archivos

## 📊 Verificación de calidad

- **77 tests pasando** (70 originales + 7 nuevos de integración y carga)
- **Ruff lint: 0 errores**
- **Smoke test: OK** (72 películas, 63 LUTs, backend operativo)

## 🔑 Notarización oficial de Apple (pendiente de configuración)

Para eliminar la advertencia de Gatekeeper completamente, se requiere:

1. Cuenta de Apple Developer (USD 99/año)
2. Configurar secretos en GitHub:
   - `MACOS_CERTIFICATE` (certificado .p12 en base64)
   - `MACOS_CERT_PASSWORD`
   - `APPLE_ID`
   - `APPLE_APP_SPECIFIC_PASSWORD`
   - `APPLE_TEAM_ID`
   - `MACOS_IDENTITY`
3. El workflow `.github/workflows/release.yml` ya incluye los pasos de `codesign` y `notarytool`

## 📋 Checksums SHA-256

| Plataforma | Archivo | SHA-256 |
|------------|---------|---------|
| macOS ARM64 | `Haluro-2.5.0-macOS-arm64.dmg` | `1116b3e5bdd6407e0b6cd701ddf205db269ee5f789619fd1b66ab87730f392fb` |
| macOS Intel | `Haluro-2.5.0-macOS-x86_64.dmg` | *(construido por CI)* |
| Windows x64 | `Haluro-Setup-2.5.0-Win11-x64.exe` | *(construido por CI)* |
| Windows Portable | `Haluro-Portable-2.5.0-Win11-x64.zip` | *(construido por CI)* |

## 🏗️ Construido con

- Python 3.13, Flask + Waitress (backend local)
- pywebview (WebView2 en Windows / Cocoa WebKit en macOS)
- Pillow, NumPy, SciPy, rawpy (procesamiento de imagen 16-bit)
- PyInstaller (empaquetado nativo)

---

*Haluro — Laboratorio Analógico Digital v2.5.0  
César Fernández Ardiles · Oregano · Chile  
Licencia MIT · https://github.com/Hermesuser/haluro*
