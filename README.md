# Haluro — Laboratorio Analógico Digital (v2.4.0)

[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-orange.svg)](LICENSE)
[![Plataformas](https://img.shields.io/badge/Plataformas-macOS%20%7C%20Windows%2011-blue.svg)](#requisitos-técnicos)
[![Tests](https://img.shields.io/badge/Tests-25%20Passing-emerald.svg)](tests/)
[![Seguridad](https://img.shields.io/badge/pip--audit-0%20Vulnerabilidades-brightgreen.svg)](#seguridad-y-privacidad)
[![Privacidad](https://img.shields.io/badge/Privacidad-100%25%20Local%20%26%20Offline-success.svg)](#seguridad-y-privacidad)
[![Edición](https://img.shields.io/badge/Edición-100%25%20No%20Destructiva-blueviolet.svg)](#filosofía-de-diseño)

> **Desarrollador y Autor:** Fotógrafo **César Fernández Ardiles**  
> **Estudio / Origen:** Oregano · Chile  
> **Propósito:** Software libre, gratuito y de código abierto para fotógrafos analógicos, laboratorios independientes y creadores visuales.  
> **Documentación Oficial:** 📖 [Manual de Uso y Guía de Cuarto Oscuro](MANUAL_DE_USO.md) · 🖨️ [Guía Web Interactiva e Imprimible](manual.html)

---

## Índice

1. [¿Qué es Haluro?](#qué-es-haluro)
2. [Filosofía de Diseño y Calidad](#filosofía-de-diseño-y-calidad)
3. [Módulos y Características](#módulos-y-características)
4. [Requisitos Técnicos](#requisitos-técnicos)
5. [Instalación y Ejecución](#instalación-y-ejecución)
   - [macOS (Nativo Apple Silicon / Intel)](#a-macos-nativo)
   - [Windows 11 (Nativo x64)](#b-windows-11-nativo)
   - [Línea de Comandos (CLI)](#c-interfaz-de-línea-de-comandos-cli)
6. [Flujo de Trabajo Paso a Paso](#flujo-de-trabajo-paso-a-paso)
7. [Seguridad, Privacidad y Rendimiento](#seguridad-privacidad-y-rendimiento)
8. [Cumplimiento Legal y Derechos de Autor](#cumplimiento-legal-y-derechos-de-autor)
9. [Guía para Publicar en GitHub](#guía-para-publicar-en-github)
10. [Créditos y Agradecimientos](#créditos-y-agradecimientos)

---

## ¿Qué es Haluro?

**Haluro** es una estación de trabajo fotográfica de escritorio nativa para **macOS** y **Windows 11** concebida desde la experiencia directa en cuarto oscuro químico. Combina la sensitometría clásica de haluros de plata con procesamiento de color en coma flotante de 16 bits para resolver dos necesidades fundamentales de la fotografía analógica contemporánea:

1. **Emulación Analógica Auténtica:** Simulación espectral de **72 películas químicas clásicas** (Kodak Portra, Tri-X, Ektachrome, Fuji Velvia, Provia, Neopan, Ilford HP5+, Delta, CineStill 800T, etc.) mediante matrices de interpolación tetraédrica 3D LUT, grano volumétrico no repetitivo, halo rojo de capa antihalo y viñeteo óptico.
2. **Revelado Digital de Negativos:** Inversión sensitométrica basada en el modelo **Hurter–Driffield (H&D)** para negativos color (C-41) y blanco y negro digitalizados mediante escáner plano, escáner dedicado de película o cámara digital con fuente de luz LED. Elimina matemáticamente la máscara naranja (D-min), desacopla el balance de blancos de la escena y emula la respuesta tonal de papeles fotográficos tradicionales (**Fuji Crystal Archive RA-4**, **Kodak Vision 2383 ECP** de cine, Minilabs **Noritsu / Frontier** y perfil logarítmico **V-Log**).

<img width="1507" height="892" alt="image" src="https://github.com/user-attachments/assets/799a98b0-341f-42d2-a1ae-2a63a6a0799f" />


<img width="1512" height="889" alt="image" src="https://github.com/user-attachments/assets/574916ec-7748-4fe2-b841-cbb806056818" />

---

## Filosofía de Diseño y Calidad

- **Edición 100% No Destructiva:** Los archivos originales cargados (`.CR2`, `.CR3`, `.NEF`, `.ARW`, `.DNG`, `.TIFF`, `.PNG`, `.JPG`, `.HEIF`) jamás son modificados, sobreescritos ni alterados. Haluro genera copias maestras independientes preservando la integridad del negativo digital.
- **100% Local y Privado:** No requiere cuenta de usuario, no utiliza conexión a la nube, no envía telemetría ni recopila datos personales. Todo el cómputo se realiza en tu procesador mediante la interfaz de bucle invertido local (`127.0.0.1`).
- **Paridad Nativa entre Sistemas Operativos:** En macOS se integra con **Cocoa WebKit**, aceleración Retina y atajos `⌘`. En Windows 11 utiliza **Microsoft Edge WebView2**, soporte por monitor v2 High-DPI, barra de título oscura integrada mediante DWM (Desktop Window Manager) y atajos `Ctrl`.
- **Exportación Maestra en 16 bits Reales:** Soporta guardado en **TIFF 48-bit RGB real** (`uint16` por canal) con compresión Adobe Deflate sin pérdida a 300 DPI, además de PNG y JPEG 4:4:4.
- **Ficha Técnica Analógica EXIF Nativa:** Inyecta en las etiquetas EXIF Sub-IFD estándar la cámara analógica utilizada, objetivo, emulsión, formato de rollo, ISO de exposición, proceso químico de revelado, modelo de escáner y autoría.

---

## Módulos y Características

### Módulo 1 — Laboratorio B&N: Virados Químicos y Papeles *Fine-Art*
- **10 Procesos de Virado Químico Real:**
  - `neutral` (Plata pura neutra sobre base blanca).
  - `selenium_1`, `selenium_2`, `selenium_3` (Virado al selenio en tres grados de profundidad: sutil, clásico y profundo).
  - `palladium` (Platino / Paladio cálido de rango dinámico extendido).
  - `sepia_sulfide` (Virado al sulfuro tradicional con medios tonos ocres).
  - `copper_iron` (Virado al cobre/hierro rojizo).
  - `warmtone_foma` (Emulsión de clorobromuro sobre papel baritado cálido).
  - `cooltone` (Bromuro de plata frío con sombras azuladas profundas).
  - `cotton_matte` (Papel 100% algodón mate con negros abiertos y textura suave).
- Control continuo de intensidad (`0%` a `150%`) y preservación tonal de la base de papel.

### Módulo 2 — Análisis Unificado de Rollo (*Roll Analysis*)
- Calibración densitométrica unificada para múltiples fotogramas de un mismo carrete.
- Evita el desagradable **"bombeo de exposición"** (*exposure pumping*) entre tomas con iluminaciones dispares.
- Modos de equilibrio de color: `dynamic` (balance independiente por toma), `shadow_weighted` (prioridad a sombras profundas) y `roll_locked` (bloqueo densitométrico estricto del rollo analizado).
- Perfiles de origen de captura: `camera_raw` (digitalización con cámara mirrorless/DSLR), `scanner_raw` (escaneo lineal sin procesar) y `flatbed_tiff` (escáner plano EPSON/Canon).
- Regulador óptico de **Pre-Saturación** (`0.50x` a `1.60x`) aplicado en el espacio de exposición logarítmica Hurter–Driffield.

### Módulo 3 — Etalonaje CMY de 3 Vías y Recorte Protegido
- Corrección de color de laboratorio mediante filtrado sustractivo **Cian**, **Magenta** y **Amarillo** (CMY).
- Ruedas tonales independientes: **Global**, **Sombras**, **Medios Tonos** y **Altas Luces**, con umbrales configurables de rango tonal.
- **Color-Protected Soft Clip:** Deslizadores de recorte de punto negro (`black_clip`) y blanco (`white_clip`) con protección cromática activa (`clip_protect`) para impedir cambios bruscos de matiz o tintes no deseados en sombras profundas y altas luces especulares.

### Módulo 4 — Acabados de Copia (*Print Finishing*)
- 8 estilos de acabado posterior a la inversión:
  - `crystal_archive` (Papel comercial Fuji Crystal Archive).
  - `portra_airy` (Altas luces abiertas y tonos de piel luminosos).
  - `gold_warm` (Calidez dorada de emulsión doméstica).
  - `superia_cool` (Copia fría contemporánea).
  - `cine_halation` (Resplandor cálido en transición de altas luces).
  - `portrait_soft` (Contraste atenuado para retrato).
  - `clean_contrast` (Contraste nítido para fotografía de calle y arquitectura).
- Variantes tonales asimétricas: `standard`, `linear`, `vivid`, `highlight_soft` y `shadow_soft`.

### Módulo 5 — Nitidez Óptica de Cuarto Oscuro en Luminancia
- Filtro de acutancia selectiva aplicada en el canal de luminancia (Y) en modos `lab` o `scanner`.
- Protección anti-grano adaptativa: modula la ganancia en función de la luminancia para no amplificar el ruido de fondo en sombras ni estropear la textura orgánica del grano de película.

### Módulo 6 — Ficha Técnica Analógica EXIF y Exportación Maestra
- Inyección EXIF nativa en metadatos estándar (`Make`, `Model`, `LensModel`, `ISOSpeedRatings`, `Artist`, `ImageDescription` y `UserComment` Unicode UTF-16).
- Autocompletado con sugerencias rápidas para cámaras clásicas (Leica, Hasselblad, Pentax, Canon, Nikon, Mamiya, Rolleiflex) y películas reconocidas.
- Botón **"Copiar pie técnico"** para pegar la ficha completa en redes sociales, bitácoras o catálogos de exposición.
- Exportación directa a `~/Downloads` con atajo `⌘S` / `Ctrl+S`, diálogo nativo de guardado `Guardar como…` con `⇧⌘S` / `Ctrl+Shift+S`, o revelado por lotes de todo el rollo con generación automática de **Hoja de Contactos** tipográfica.

---

## Requisitos Técnicos

### Para macOS
- **Sistema Operativo:** macOS 11.0 (Big Sur) o superior (macOS 12 Monterey, macOS 13 Ventura, macOS 14 Sonoma, macOS 15 Sequoia).
- **Arquitectura:** Apple Silicon nativo (`arm64` — M1, M2, M3, M4) o procesadores Intel (`x86_64`).
- **Motor Webview:** WebKit nativo incluido en el sistema operativo (no requiere Chromium ni Electron).

### Para Windows 11
- **Sistema Operativo:** Windows 11 (64-bit) o Windows 10 Versión 2004+ (Build 19041+).
- **Arquitectura:** x64 o ARM64 (mediante emulación nativa de Windows 11).
- **Motor Webview:** **Microsoft Edge WebView2 Runtime** (preinstalado de fábrica en todas las ediciones de Windows 11).
- **Interfaz Gráfica:** Integración con DWM Dark Mode y compatibilidad con monitores de alta densidad de píxeles (High-DPI v2).

### Hardware Recomendado
- **Memoria RAM:** 8 GB mínimo (16 GB recomendado para digitalizaciones RAW de 45+ megapíxeles).
- **Almacenamiento:** 250 MB de espacio libre en disco para la aplicación.
- **Pantalla:** Calibrada en espacio sRGB o Display-P3 (mínimo 1280×800, óptimo 1920×1080 o superior).

---

## Instalación y Ejecución

### A) macOS (Nativo)

#### Opción 1: Imagen de Disco Oficial (.dmg)
1. Descarga la versión adecuada para tu procesador desde [Releases de GitHub](https://github.com/Hermesuser/haluro/releases):
   - **Apple Silicon (M1 / M2 / M3 / M4):** `Haluro-2.4.0-macOS-arm64.dmg`
   - **Procesadores Intel (Core i5 / i7 / i9 / Xeon):** `Haluro-2.4.0-macOS-x86_64.dmg`
2. Haz doble clic sobre el archivo `.dmg` montado y arrastra el icono de **Haluro** hacia tu carpeta de **Aplicaciones**.
3. Abre **Haluro** desde Launchpad, Spotlight o tu carpeta de **Aplicaciones**.
   > **Nota para el primer arranque en macOS Sequoia / Sonoma:**  
   > Al ser una aplicación artesanal e independiente, Gatekeeper puede mostrar un cartel preventivo (*«Apple no pudo verificar que Haluro no contenga software malicioso»*). Para autorizarla por única vez:
   > 1. Haz clic en **«Listo»** en el cuadro de diálogo.
   > 2. Abre **Ajustes del Sistema  > Privacidad y seguridad** y baja hasta el apartado **Seguridad**.
   > 3. Haz clic en el botón **«Abrir de todos modos»** y confirma con tu contraseña o Touch ID.  
   > *(Alternativa rápida en Terminal: `xattr -cr /Applications/Haluro.app`)*. A partir de ese momento abrirá de forma normal con doble clic.

#### Opción 2: Ejecución desde código fuente
```bash
# Clonar el repositorio
git clone https://github.com/Hermesuser/haluro.git
cd haluro

# Ejecutar el lanzador nativo de macOS
chmod +x run.sh
./run.sh
```

---

### B) Windows 11 (Nativo)

#### Opción 1: Instalador Moderno (Setup .exe)
1. Descarga `Haluro-Setup-2.4.0-Win11-x64.exe` desde las Releases de GitHub.
2. Ejecuta el instalador. No requiere permisos de administrador obligatorios (instalación por usuario limpia y sin fricción UAC).
3. Inicia Haluro desde el Menú Inicio o el acceso directo del Escritorio.

#### Opción 2: Versión Portátil (.zip)
1. Descarga `Haluro-Portable-2.4.0-Win11-x64.zip`.
2. Descomprime la carpeta en cualquier ubicación (por ejemplo, `C:\Programas\Haluro`).
3. Ejecuta directamente `Haluro.exe`.

#### Opción 3: Ejecución desde código fuente en Windows 11
```cmd
:: En una consola de Windows o PowerShell dentro de la carpeta del proyecto
run_windows.bat
```

---

### C) Interfaz de Línea de Comandos (CLI)

Haluro incluye una potente interfaz CLI sin interfaz gráfica para automatizaciones y servidores:

```bash
# Consultar versión y autor
python cli.py --version
python cli.py about

# Listar las 72 emulsiones disponibles agrupadas por proceso
python cli.py list --category neg

# Emular película sobre una fotografía RAW
python cli.py develop captura.cr2 --film portra400 --format tiff --out ./reveladas

# Revelar un negativo C-41 digitalizado con cámara
python cli.py invert negativo_01.tif \
  --profile frontier \
  --scan-source camera_raw \
  --tone highlight_soft \
  --print-finish crystal_archive \
  --format tiff \
  --camera "Leica M6" \
  --film-stock "Kodak Portra 400" \
  --iso 400 \
  --out ./positivos
```

---

## Flujo de Trabajo Paso a Paso

```
                   ┌─────────────────────────────────────────┐
                   │    Importar RAW / TIFF / DNG / JPG       │
                   └────────────────────┬────────────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
     [Modo 1: Emulación 72 Films]                  [Modo 2: Revelado Negativo]
     - Selección de emulsión química               - Selección de fuente (Cámara / Escáner)
     - Compensación EV (-2.0 a +2.0)               - Cuentagotas de soporte base (D-min)
     - Control de Halo (Antihalo)                  - Balance de blancos neutro de escena
     - Grano analógico y viñeteo                   - Calibración de rollo (Roll Analysis)
     - Fecha analógica en emulsión                 - Virados B&N / Acabados de copia
                 │                                 - Etalonaje CMY de 3 vías
                 │                                             │
                 └──────────────────────┬──────────────────────┘
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  Ficha Técnica Analógica EXIF Nativa    │
                   │  (Cámara, Objetivo, Rollo, ISO, Autor)  │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │    Exportación Maestra No Destructiva    │
                   │  (TIFF 16-bit real · PNG · JPEG 4:4:4)  │
                   └─────────────────────────────────────────┘
```

---

## Seguridad, Privacidad y Rendimiento

1. **Aislamiento de Red:** Haluro no realiza ninguna petición externa a Internet en tiempo de ejecución. Las tipografías (*Plus Jakarta Sans* y *JetBrains Mono*) están alojadas localmente en el paquete en formato WOFF2.
2. **Política de Seguridad de Contenido (CSP):**
   ```http
   Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none';
   ```
3. **Auditoría de Vulnerabilidades (`pip-audit`):** El entorno de ejecución utiliza `Pillow >= 13.0.0` y `pytest >= 9.0.0`, resolviendo todas las advertencias y CVEs conocidas del ecosistema Python (resultado: **0 vulnerabilidades detectadas**).
4. **Validación de Rutas Seguras:** Todas las rutas de importación y exportación son verificadas contra ataques de salto de directorio (*path traversal*) mediante resolución canónica y extensiones permitidas.
5. **Calidad de Código y Pruebas Automatizadas:** Suite de **25 pruebas unitarias e integrales** que verifican matemáticamente la inversión H&D, la neutralidad del balance de blancos, la integridad de 16 bits de los archivos TIFF y la persistencia EXIF.

---

## Cumplimiento Legal y Derechos de Autor

Haluro ha sido desarrollado con estricto apego al marco legal internacional de software libre y propiedad intelectual:

- **Código Fuente:** Licenciado bajo la **Licencia MIT** (Copyright &copy; 2026 César Fernández Ardiles, Oregano, Chile).
- **Tablas de Emulación 3D (CLUTs):** Las tablas de color incluidas en `luts/` provienen de la colección de simulación de película de código abierto desarrollada por **Pat David (PIXLS.US)**, **GREYC/G'MIC** y **RawTherapee**, distribuidas bajo licencia **Creative Commons Atribución-CompartirIgual 4.0 Internacional (CC BY-SA 4.0)**.
- **Tipografías:** Distribuidas bajo la licencia **SIL Open Font License 1.1** (OFL).
- **Cláusula de Marcas Nominativas:** Nombres como *Kodak, Fujifilm, Ilford, Agfa, CineStill, Rollei, Noritsu, Frontier, Foma* o *Adobe* se citan exclusivamente de forma informativa (*nominative fair use*) para describir el tipo de material analógico que el software aproxima. Haluro es un proyecto independiente y no cuenta con afiliación, patrocinio ni respaldo de dichas compañías.
- Consulta el archivo [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) para el detalle pormenorizado de cada componente.

---

## Guía para Publicar en GitHub

Para llevar este proyecto a tu cuenta de GitHub, sigue estos sencillos pasos desde la terminal:

### 1. Inicializar el repositorio Git local
```bash
cd /Users/cefernan/Documents/Antigravity/mfilm-darkrooms

# Inicializar Git si aún no se ha hecho
git init -b main

# Configurar tu identidad de autor
git config user.name "César Fernández Ardiles"
git config user.email "tu-correo@ejemplo.com"
```

### 2. Verificar el estado y realizar el commit inicial
```bash
git add .
git commit -m "feat: release Haluro v2.4.0 — Laboratorio Analógico Digital"
```

### 3. Crear el repositorio en GitHub y subir los archivos
1. Ingresa a [GitHub.com/new](https://github.com/new) y crea un repositorio público llamado `haluro`.
2. Conecta el repositorio remoto y sube la rama principal:
```bash
git remote add origin https://github.com/TU_USUARIO/haluro.git
git branch -M main
git push -u origin main
```

### 4. Publicar un Release Oficial con los Instaladores
Haluro incluye un flujo de integración continua en `.github/workflows/release.yml`. Para compilar y publicar automáticamente los binarios nativos para macOS y Windows 11:
```bash
# Crear la etiqueta de versión
git tag -a v2.4.0 -m "Haluro v2.4.0 — Producción y Distribución Gratuita"

# Subir la etiqueta a GitHub
git push origin v2.4.0
```
GitHub Actions ejecutará las pruebas automáticas (`pytest`), la auditoría de seguridad (`pip-audit`) y compilará los paquetes `.dmg` e instaladores `.exe` adjuntándolos automáticamente al Release en GitHub.

---

## Créditos y Agradecimientos

- **César Fernández Ardiles** (Fotógrafo y desarrollador, Oregano · Chile): Diseño de arquitectura, implementación sensitométrica Hurter-Driffield, interfaz de usuario y desarrollo general.
- **Pat David & Comunidad PIXLS.US / RawTherapee / G'MIC**: Por su pionera labor en la documentación y preservación del color analógico en software libre.
- **Maik Riechert & Equipo de LibRaw**: Por el extraordinario motor de decodificación de archivos RAW fotográficos.
- **Equipo de pywebview & Pallets (Flask)**: Por proporcionar las bases ligeras para crear aplicaciones de escritorio desacopladas de Chromium.

---

<p align="center">
  <strong>Haluro — Preservando la nobleza y la alquimia de la fotografía analógica en la era digital.</strong><br>
  Hecho con dedicación en Chile · 2026
</p>
