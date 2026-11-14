# Registro de Cambios, Propuestas y Avances — Haluro

Este documento mantiene el registro vivo de **investigación, propuestas de mejora, decisiones de aprobación y avance de implementación** del proyecto **Haluro** (`/Users/cefernan/Documents/Antigravity/mfilm-darkrooms`), complementando a [CHANGELOG.md](../CHANGELOG.md) (que documenta las versiones publicadas).

---

## Estado Base del Proyecto (Línea Base)

- **Versión actual:** `2.8.0` (fuente canónica: [engine/**init**.py](../engine/__init__.py))
- **Línea base previa a este ciclo:** `2.7.0` (`4f7e146`, `chore: revert local exposure masks feature and downgrade version to 2.7.0`)
- **Capacidades principales implementadas hasta v2.8.0:**
  - **Modo «Emulación · 80»** ([engine/films.py](../engine/films.py), [engine/pipeline.py](../engine/pipeline.py)): 80 películas químicas vía LUT 3D y modelos matemáticos, grano determinista por semilla, proceso químico (*Normal*, *Stand / Rodinal*, *Push +1/+2*, *Pull −1*), halación, viñeteo, sello de fecha en cuarzo, **Zonas tonales** (v2.6.0), **Curva tonal por canal** (`rgb`, `l`, `r`, `g`, `b`) (v2.7.0) y **Marginador de cuarto oscuro (Easel Borders + Dry-Down)**.
  - **Modo «Revelar negativo»** ([engine/negative_inverter.py](../engine/negative_inverter.py)): inversión sensitométrica Hurter–Driffield (`T = 10^-D`), perfiles de sustrato (`c41_orange`, `clear_base`, `phoenix`, `warm_base`, `creative_switch`), calibración *Flat-Field* LED, detección automática y muestreo manual de soporte base (`D-min`), conservación de rebordes/sprockets y visor geométrico, positivado B&N *Split Grade* + *Pre-flashing*, limpieza puntual de motas sin IR, análisis unificado de rollo, perfiles de minilab/papel, 8 acabados de copia, 10 virados químicos B&N, etalonaje CMY de 3 vías, Curva tonal + Tira f-stop de 5 bandas, nitidez óptica en luminancia (`lab`, `scanner`), `border_buffer` y `crop_pct`.
  - **Mesa de luz y salida** ([engine/contact_sheet.py](../engine/contact_sheet.py), [engine/roll_processor.py](../engine/roll_processor.py)): hoja de contactos interactiva con zoom y 3–6 columnas, vista *Esencial (Minilab)* vs *Completa* + atajos estilo Frontier, calculadora de reciprocidad de Schwarzschild y presets químicos EXIF, procesamiento multinúcleo de rollo completo, exportación TIFF 16-bit (48-bit RGB Adobe Deflate), PNG y JPEG 4:4:4, inyección EXIF analógica nativa, sesión local protegida (Waitress + CSRF + loopback).

---

## Bitácora de Sesiones y Avances

### 2026-11-14 — Estudio del cuaderno «Disparafilm» (NotebookLM) y auditoría de oportunidades

- **Fuente consultada:** Cuaderno NotebookLM `Disparafilm` (ID `4e899600-6151-48db-afca-57506ceaae3e`, 167 fuentes de vídeo sobre procesos químicos, positivado en cuarto oscuro, digitalización de negativos, software de inversión y emulsiones contemporáneas).
- **Auditoría cruzada:** Se compararon los flujos y fricciones documentadas en Disparafilm contra los módulos actuales de Haluro v2.7.0 (`engine/`, `app.py`, `templates/index.html`, `static/js/app.js`).
- **Resultado:** Se formularon **9 propuestas concretas (`P1`–`P9`)**, pendientes de aprobación del autor antes de escribir código.

### 2026-11-14 (P1) — Perfiles de sustrato y películas atípicas sin máscara naranja

- **Estado:** Implementada y verificada (`pytest`: 85/85 OK, `ruff check .`: OK, `check_version.py`: OK).
- **Cambios realizados:**
  - `engine/negative_inverter.py`: Se añadió el registro `FILM_SUBSTRATES` y `list_film_substrates()` con 5 perfiles (`c41_orange` por defecto con compatibilidad retroactiva exacta, `clear_base` para Aerocolor IV/SantaColor/cine sin remjet, `phoenix` para Harman Phoenix I/II con acoplamiento de canales, suavizado de contraste y compensación de cruce cromático magenta/luces, `warm_base` para Lomo '92/Redscale y `creative_switch` para Harman Azure/Lomo Purple/Metropolis). Se integró `film_substrate` en `auto_detect_film_base`, `_compute_normalized_log_exposure`, `analyze_roll_calibration`, `compute_neutral_wb_from_point`, `auto_balance_scene_wb` e `invert_negative`.
  - `app.py`: Exposición de `film_substrates` en `/api/negative/profiles`, validación de `film_substrate` en `_parse_negative_params` y `/api/negative/auto_detect_base`, paso completo a análisis de rollo, cuentagotas WB, auto-balance, previsualización y exportación/sidecar `.meta.json`.
  - `templates/index.html` y `static/js/app.js`: Selector `#negSubstrateSelect` dentro de `Proceso y captura` (visible en modo Color C-41) con descripción contextual, persistencia en receta por fotograma, sincronización de rollo, undo/redo y preferencias locales.
  - `tests/test_disparafilm_features.py`: Suite nueva con 4 tests unitarios y de integración Flask para `P1` (compatibilidad retroactiva, detección en base clara, preservación de paleta en emulsiones creativas, fallback seguro en API).

### 2026-11-14 (P2) — Visor de zona de cálculo y modo «Conservar reborde (Sprockets)»

- **Estado:** Implementada y verificada (`pytest`: 86/86 OK, `ruff check .`: OK, `check_version.py`: OK).
- **Cambios realizados:**
  - `engine/negative_inverter.py`: Se añadió `keep_sprockets: bool = False` a `_compute_normalized_log_exposure`, `analyze_roll_calibration`, `compute_neutral_wb_from_point`, `auto_balance_scene_wb` e `invert_negative`. Cuando está activo, protege el reborde y perforaciones manteniendo salida sin recorte (`crop_pct = 0`) y ampliando el margen interno de análisis densitométrico y balance neutro (`≥12%` y `≥14%`).
  - `app.py`: Validación de `keep_sprockets` en `_parse_negative_params`, alineación del fotograma original sin recorte cuando `keep_sprockets=True` en `/api/negative/preview`, paso a análisis de rollo/WB y guardado en historial `.meta.json`.
  - `templates/index.html`, `static/css/style.css` y `static/js/app.js`: Interruptores `#negKeepSprocketsToggle` y `#negShowBorderGuideToggle` en *Análisis de rollo y márgenes*, bloqueo visual del deslizador de recorte cuando se conservan sprockets y superposición geométrica exacta `#borderGuideOverlay` en el visor (visible de forma continua o automática durante el ajuste de márgenes).
  - `tests/test_disparafilm_features.py`: Tests de integración y motor verificando preservación de dimensiones con rebordes/perforaciones extremos y estabilidad en API Flask.

### 2026-11-14 (P3) — Calibración de campo plano (*Flat-Field*) de mesa LED y viñeteo

- **Estado:** Implementada y verificada (`pytest`: 87/87 OK, `ruff check .`: OK, `check_version.py`: OK).
- **Cambios realizados:**
  - `engine/negative_inverter.py`: Se implementaron `compute_flat_field_gain_map()` (suavizado gaussiano + rejilla 64×64 de ganancia inversa respecto al núcleo central con métricas de caída en esquinas y uniformidad), `_upsample_gain_grid()` en precisión `float32`, `apply_flat_field_correction()` y caché `resolve_flat_field_gain()`. Integrado antes de la resta de máscara D-min en `auto_detect_film_base`, `analyze_roll_calibration`, `_compute_normalized_log_exposure`, `compute_neutral_wb_from_point`, `auto_balance_scene_wb`, `invert_negative` y `process_negative_to_image`.
  - `app.py` y `engine/roll_processor.py`: Endpoint `/api/negative/flat_field/upload` con validación estricta de formato e imagen legible, validación segura de `flat_field_file` vía `_resolve_source_file`, parámetro `flat_field_strength` (`0%`–`150%`), soporte completo en `RollBatchJob` (modo negativo por lote) y guardado en historial `.meta.json`.
  - `templates/index.html` y `static/js/app.js`: Botones `Cargar toma en blanco` y `Quitar`, lectura de caída de esquinas/uniformidad, deslizador `#negFlatFieldStrengthSlider`, sincronización de rollo y undo/redo.
  - `tests/test_disparafilm_features.py`: Tests con mapa de viñeteo radial sintético, carga multipart en `/api/negative/flat_field/upload` y defensa frente a path traversal.

### 2026-11-14 (P4) — Positivado B&N *Split Grade* (Filtro 00 + Filtro 5) y *Pre-flashing* digital

- **Estado:** Implementada y verificada (`pytest`: 88/88 OK, `ruff check .`: OK, `node --check`: OK, `check_version.py`: OK).
- **Cambios realizados:**
  - `engine/negative_inverter.py`: Se añadió `_apply_bw_split_grade_and_preflash(y_lin, grade00, grade5, preflash)` antes del virado químico en la rama `is_bw`. Emula el positivado en papel multigrado variable (*Filtro 00* para altas luces/hombro suave, *Filtro 5* para negros profundos y contraste bajo, y *Pre-flashing* para vencer la inercia de papel en luces duras) manteniendo compatibilidad bit a bit cuando los controles están en cero e ignorándose limpiamente en color.
  - `app.py`: Validación segura de `bw_grade00`, `bw_grade5` (`-1.0..+1.0`) y `bw_preflash` (`0.0..1.0`) en `_parse_negative_params`, más registro en `.meta.json`.
  - `templates/index.html` y `static/js/app.js`: Controles contextuales dentro de `#negBwChemPanel` (visibles solo en `Plata B&N`) con botón rápido de reseteo `#resetBwSplitBtn`, persistencia por fotograma, sincronización de rollo, preferencias y undo/redo.
  - `tests/test_disparafilm_features.py`: Tests unitarios y de endpoint `/api/negative/preview` verificando neutralidad en cero, comportamiento tonal independiente en altas/sombras, aislamiento frente a modo color y API B&N.

### 2026-11-14 (P5) — Curva tonal en `Revelar negativo` y modo «Tira f-stop» de 5 bandas

- **Estado:** Implementada y verificada (`pytest`, `ruff`, `node --check`).
- **Cambios realizados:**
  - `engine/negative_inverter.py`: Curva tonal PCHIP compartida (`_normalize_curve_points`, `apply_tone_curve`) aplicada en el positivo revelado antes de la salida final y modo `build_fstop_test_strip()` (5 bandas en pasos relativos de exposición configurables).
  - `app.py`, `engine/roll_processor.py`, `templates/index.html`, `static/js/app.js`: Soporte de `curve_points` y `fstop_strip`/`fstop_step_ev` en previsualización, exportación, batch y controles de UI compartidos.
  - `tests/test_disparafilm_features.py`: Tests unitarios y E2E para curva tonal y tira f-stop en modo negativo.

### 2026-11-14 (P6) — 8 nuevas emulsiones contemporáneas (`80` películas) y procesos químicos (*Stand / Rodinal*, *Push*, *Pull*)

- **Estado:** Implementada y verificada (`pytest`, `ruff`, `node --check`).
- **Cambios realizados:**
  - `engine/films.py`: Catálogo ampliado de `72` a `80` emulsiones incluyendo Kodak Gold 200 (Nueva fórmula), Fujifilm 400 (EE. UU.), Harman Phoenix 200, Harman Phoenix II 200, Cinestill 400D, ORWO Wolfen NC500, Flic Film Elektra 100 (Aerocolor IV) e Ilford Kentmere 400.
  - `engine/pipeline.py`, `app.py`, `engine/roll_processor.py`, `templates/index.html`, `static/js/app.js`: Parámetro `dev_process` (`normal`, `stand_rodinal`, `push_1`, `push_2`, `pull_1`) con acutancia por máscara unsharp, realce tonal y modificación determinista de grano; etiqueta actualizada a `Emulación · 80`.

### 2026-11-14 (P7) — Flujo rápido estilo Minilab (*Vista Esencial* vs *Completa* + atajos tipo Fuji Frontier)

- **Estado:** Implementada y verificada (`node --check`, `pytest`).
- **Cambios realizados:**
  - `templates/index.html`, `static/css/style.css`, `static/js/app.js`: Conmutador *Esencial / Completa* persistente (`localStorage`), atajos de teclado estilo Minilab para corrección rápida YMC/densidad y navegación agilizada por fotogramas.

### 2026-11-14 (P8) — Limpieza puntual de polvo/motas (sin IR) y calculadora de reciprocidad + presets químicos EXIF

- **Estado:** Implementada y verificada (`pytest`, `ruff`).
- **Cambios realizados:**
  - `engine/pipeline.py`, `engine/negative_inverter.py`, `app.py`, `engine/roll_processor.py`: Reparación localizada determinista de motas/polvo (`dust_spots` en coordenadas normalizadas `x, y, radius`) mediante interpolación/mediana anular sin canal infrarrojo, compatible con negativos B&N y color tanto en vista previa como en exportación y lote.
  - `templates/index.html`, `static/js/app.js`: Herramienta interactiva de marcado/deshacer de motas en el visor, calculadora de compensación de reciprocidad de Schwarzschild y presets químicos en la ficha técnica EXIF.

### 2026-11-14 (P9) — Marginador de cuarto oscuro (*Easel Borders* + *Dry-Down*) y fijación dimensional de exportación

- **Estado:** Implementada y verificada (`pytest`: 94 passed, `ruff`, `node --check`).
- **Cambios realizados:**
  - `engine/pipeline.py`, `engine/negative_inverter.py`, `app.py`, `engine/roll_processor.py`: Parámetros `dry_down_comp`, `easel_border_pct`, `easel_border_color` (`white`, `offwhite`, `black`) y corrección en `save_output_image()` para devolver el `pil_img` final con dimensiones reales post-marginador en respuestas API e historial.
  - `tests/test_disparafilm_features.py`: `test_p9_easel_borders_and_dry_down_export` validando *dry-down*, márgenes y dimensiones reales en exportación E2E.

### 2026-11-14 — v2.8.0 Depuración, eliminación de restos de Máscaras de Exposición, compilación y control de versiones

- **Limpieza de restos inacabados (*Máscaras de exposición / Dodge & Burn*):**
  - `engine/pipeline.py`: Eliminada función muerta `apply_local_exposure_offset(display, mask, ev_offset)` sin llamadores en el repositorio.
  - `static/css/style.css`: Eliminado comentario huérfano `/* LOCAL EXPOSURE MASKS (digital dodge & burn) */`.
  - `README.md` y `MANUAL_DE_USO.md`: Eliminadas secciones residuales de «Máscaras de exposición local (Dodge & Burn digital)» y sincronizado el catálogo de `72` a `80` películas.
- **Depuración y calidad de código:**
  - `static/js/app.js`: Eliminadas 8 llamadas redundantes a `updateDustSpotsUI()`; texto de copia *Acerca de* actualizado dinámicamente a la versión activa y `80 películas químicas`.
  - `engine/`, `app.py`, `tests/`: Limpieza automática de espacios en blanco (`ruff check --select W291,W293,W391 --fix`; 50 correcciones) y verificación completa con `ruff check .` (`E, F, B, I, UP, S`).
  - `haluro.spec`: Agregado `engine.roll_processor` explícitamente en `hidden_imports`.
- **Versionado (`2.7.0` → `2.8.0`), compilación y empaquetado macOS arm64:**
  - Actualizados `engine/__init__.py`, `pyproject.toml`, `version.json` y `CHANGELOG.md`; validado con `.github/scripts/check_version.py`.
  - Compilado bundle autónomo `dist/Haluro.app` (PyInstaller 6.22.3, smoke-test frozen validado: `films_count=80`, `luts_count=63`, `version=2.8.0`) y empaquetado `dist/Haluro-2.8.0-macOS-arm64.dmg` (SHA-256 `ef19240d28aeb7ae29f6cfe2a73681b4c8ad1349a2f9b2222901c9a429cd5274`).

---

## Banco de Propuestas

| ID | Propuesta | Área en Haluro | Complejidad estimada | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **P1** | Perfiles de sustrato y películas atípicas sin máscara naranja (Phoenix I/II, Aerocolor IV, Lomo '92, Redscale, Azure) | `Revelar negativo` (`engine/negative_inverter.py`) | Media | **Implementada** |
| **P2** | Visor de zona de cálculo + modo «Conservar reborde y perforaciones (Sprockets)» | `Revelar negativo` (`engine/negative_inverter.py`, UI) | Media | **Implementada** |
| **P3** | Calibración de campo plano (*Flat-Field*) para viñeteo y desigualdad de la mesa LED | `Revelar negativo` (`engine/negative_inverter.py`, `app.py`) | Media | **Implementada** |
| **P4** | Positivado B&N *Split Grade* (Filtro 00 + Filtro 5) y *Pre-flashing* digital | `Revelar negativo` · Rama B&N (`engine/negative_inverter.py`) | Baja-Media | **Implementada** |
| **P5** | Curva Tonal en `Revelar negativo` + Modo «Tira de prueba en fracciones de paso (f-stop)» | Ambos modos (`engine/`, `static/js/app.js`) | Media | **Implementada** |
| **P6** | Nuevas emulsiones contemporáneas (`80`) y simulación de revelado (*Stand / Rodinal*, *Push*, *Pull*) | `Emulación · 80` (`engine/films.py`, `engine/pipeline.py`) | Baja-Media | **Implementada** |
| **P7** | Flujo rápido estilo Minilab (atajos tipo Fuji Frontier + modo *Esencial* vs *Completo*) | Interfaz / UX (`static/js/app.js`, `templates/index.html`) | Baja | **Implementada** |
| **P8** | Limpieza ligera de polvo/motas (sin IR para B&N) + Calculadora de reciprocidad y presets químicos EXIF | `Revelar negativo` + Ficha EXIF (`engine/`, UI) | Media | **Implementada** |
| **P9** | Marginador de cuarto oscuro (*Easel Borders* blancos/negros + *Dry-Down*) en exportación | Exportación (`engine/pipeline.py`, `app.py`) | Baja | **Implementada** |

---

## Reglas de Registro para Próximas Iteraciones

1. Ninguna propuesta pasa a código sin aprobación explícita del usuario.
2. Cada propuesta aprobada cambiará su estado en la tabla anterior (`Aprobada` → `En progreso` → `Implementada` + tests + commit) y añadirá una entrada fechada en la bitácora.
3. Los cambios que afecten a una versión publicada seguirán documentándose además en [CHANGELOG.md](../CHANGELOG.md).
