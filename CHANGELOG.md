# Changelog

Todas las versiones relevantes de Haluro se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y
el proyecto usa [versionado semántico](https://semver.org/lang/es/).

La versión vive en un único sitio: `engine/__init__.py`. Un guardián en la CI
(`.github/scripts/check_version.py`) verifica que ninguna otra copia se desvíe.

---

## [2.11.1] — 2026-11-21

### Corregido y Mejorado
- **Cabecera del catálogo de películas:** Se eliminó el solapamiento y salto de línea en `+ LUT` y el recorte del contador con 3 dígitos (`199`) en paneles estrechos.
- **Eliminar emulsiones y Mis LUTs siempre visible:** El botón de eliminar usa ahora un icono de papelera siempre visible junto a la estrella sin solaparse sobre el badge `ISO`, y se añadió el botón **Vaciar** (`DELETE /api/user_luts`) en la barra de **Mis LUTs** para eliminar todos los `.cube` personalizados en un clic.

---

## [2.11.0] — 2026-11-21

### Añadido
- **Proyectos de rollo digital (`.haluro`):** Nuevo módulo `engine/projects.py`, endpoints `/api/projects` y modal **Proyectos** (`⌥⌘S` en macOS / `Ctrl+Alt+S` en Windows y Linux) para guardar, actualizar y retomar carretes digitales completos con copias protegidas de las imágenes originales, orden exacto de la tira, selección (`P`/`X`), emulaciones y ajustes individuales por fotograma, calibración de rollo negativo, hoja de contactos y metadatos EXIF analógicos. Incluye indicador de cambios sin guardar, aviso antes de cerrar, retomar el último proyecto en un clic, y exportación/importación de paquetes portables `.haluro` (con soporte *drag & drop* y protección *zip-slip*).
- **Gestión completa del catálogo de emulsiones:** Botón de eliminación (`×`) con confirmación en todas las emulsiones del catálogo (`DELETE /api/films/<key>`): borra archivos `.cube` para LUTs de usuario y oculta de forma persistente (`hidden_films.json`) emulsiones base con opción de deshacer y barra de restauración (`POST /api/films/restore_hidden`) sin romper proyectos guardados.

### Corregido y Mejorado
- **Empaquetado limpio de «Mis LUTs»:** Se vació `user_luts/` y se añadieron `user_luts/` y `projects/` a `.dockerignore` (y `hidden_films.json` a `.gitignore`) para garantizar que el espacio de LUTs personalizados llegue vacío al usuario final al empaquetar.
- **Pruebas automatizadas:** Nuevas suites en `tests/test_roll_projects.py` y ampliación de `tests/test_user_luts.py` (118 pruebas en total).

---

## [2.10.2] — 2026-11-16

### Corregido y Mejorado
- **Release unificado macOS + Windows 11:** Consolida las correcciones de **Dodge & Burn** (sincronización en vivo, suavizado real en graduado, tirador central, asas cardinales y atajos `Esc`/`Supr`), propagación de óptica compartida en `Sincronizar rollo`, las 10 capturas actualizadas y los últimos ajustes de documentación.

---

## [2.10.1] — 2026-11-16

### Añadido y Mejorado
- **Grano orgánico multiescala y selector por ASA (`Auto`, `100`–`6400`):** Nuevo motor `apply_grain` de 3 octavas (microcristal, cúmulo medio y macrocúmulo suave) con remuestreo bicúbico, separación física entre grano acromático B&N y nubes de colorante C-41, envolvente tonal asimétrica e invariancia de escala entre vista previa y exportación. Nuevo selector **ASA del rollo (grano)** (`100`, `200`, `400`, `800`, `1600`, `3200`, `6400`) en **Química y óptica** y flag `--grain-asa` en CLI.
- **Calibración de halación y LUTs de usuario:** Umbral suave de altas luces y halo dual en `apply_halation`, además de valores base calibrados para `.cube` de usuario.
- **Dodge & Burn y ergonomía de cuarto oscuro:** Reparada la sincronización en vivo (`triggerDebouncedPreview`), añadido **Suavizado** real en máscaras graduadas, áreas de agarre de `28 px`, tirador central para trasladar máscaras radiales/graduadas, asas cardinales en el perímetro (`Shift` circular), guías visuales de suavizado, atajos `Esc` / `Supr` y propagación de óptica compartida en `Sincronizar rollo`.
- **Documentación:** Actualización de `README.md`, `MANUAL_DE_USO.md` y `manual.html` con las 10 capturas en vivo de la `v2.10.1` (incluyendo corrección `MD033`).

---

## [2.10.0] — 2026-11-15

### Añadido
- **LUTs 3D de usuario (`.cube`):** Nueva pestaña **Mis LUTs** con importación directa (`+ LUT`) de archivos `.cube` (1D shaper y/o grilla 3D), validación previa de tablas, normalización de extensiones duplicadas (`.cube.cube`), selector de 6 espacios de color de entrada (`sRGB`, `Rec.709`, `S-Log3`, `ARRI LogC3`, `Cineon`, `Linear`) y gestión local en `user_luts/` (apertura de carpeta y eliminación individual).
- **Documentación actualizada:** Actualización de `README.md`, `MANUAL_DE_USO.md`, `manual.html` y `docs/manual.html` con captura en vivo (`docs/images/10_mis_luts_usuario.png`).

---

## [2.9.1] — 2026-11-15

### Accesibilidad (WCAG 2.2 AA) y UX/UI
- **Contraste y tokens:** Nuevo token `--border-control` (`≥ 3:1` en modo darkroom y `theme-safelight`) aplicado a inputs, selects, deslizadores e interruptores; ajuste de `--crimson-alert` (`#f25557`) y `--text-dim` en `manual.html` (`#8e96a4`) para superar `4.5:1`.
- **Objetivos interactivos ≥ 24 × 24 px:** Ampliados `.search-clear-btn`, `.step-nudge-btn`, `.fav-btn`, `.tool-icon-btn` en barras estrechas, y áreas de impacto `::after` en `.crop-handle` y `.slider`.
- **Operabilidad por teclado y semántica ARIA:** Eliminados controles interactivos anidados en `.film-card` y `.film-frame-thumb`; `.sheet-frame-hotspot` y `.crop-handle` convertidos a `<button type="button">` con soporte de flechas en recorte y en `#curveCanvas`; `.control-val` operable con `Enter`/`Espacio`; etiquetas `<label for="...">` nativas y jerarquía continua `h1 → h2 → h3` en panel derecho y modales.
- **Consistencia UI:** Unificado `#simDevProcessSelect` con `.dark-select`, unificado atajo de Mesa limpia (`⌥ ⌘ Z`) en el modal de atajos, y pruebas de regresión WCAG 2.2 AA en `tests/test_e2e_flask_client.py` y `tests/test_e2e_playwright.py`.

---

## [2.9.0] — 2026-11-15

### Añadido
- **Geometría Unificada (Emulación y Revelado de Negativos):** Recorte interactivo sobre el lienzo (ratios `free`, `original`, `1:1`, `4:3`, `3:2`, `16:9`, `5:4`, `6:7` y botón `⇄` para invertir orientación), nivelación fina (`±15°`), herramienta de **Trazar horizonte** sobre dos puntos, corrección de perspectiva vertical (`Keystone`), rotación en pasos de `90°`, volteo horizontal/vertical, auto-recorte y guías de composición (`Tercios`, `Áurea`, `Diagonal`, `Centro`) con lectura de píxeles en vivo.
- **Óptica, Limpieza y Cuarto Oscuro Local Compartido:** Disponibles tanto en **Emulación** como en **Revelado Negativos**:
  - **Limpieza de polvo y motas** (`apply_dust_spot_healing`).
  - **Reducción de ruido digital** (luminancia y crominancia) (`apply_digital_denoise`).
  - **Eliminación de aberración cromática / halos** (`apply_defringe`).
  - **Enfoque óptico de laboratorio / escáner** (`apply_optical_sharpen`: `off`, `lab`, `scanner`).
  - **Dodge & Burn local** (`apply_local_dodge_burn`) con hasta 8 máscaras interactivas de tipo **gradiente lineal** o **radial** con exposición, suavidad/pluma e inversión.
- **Preservación de Formato Original, Linear DNG 16-bit y Sidecar `.XMP`:** Nuevo formato de exportación `original` (mantiene el formato de entrada o convierte RAW a DNG lineal de 16 bits sin pérdida), exportación directa a **Linear DNG 16-bit** (`dng`) y generación automática de archivo sidecar `.xmp` con metadatos de cámara, emulsión y geometría.
- **Catálogo ampliado a 80 emulsiones:** Incorporación de nuevas películas de cine, blanco y negro y diapositiva en el catálogo.
- **Compilación macOS Intel (`x86_64`) y Apple Silicon (`arm64`):** Generación verificada de `Haluro-2.9.0-macOS-arm64.dmg` y `Haluro-2.9.0-macOS-x86_64.dmg`.

### Corregido y Mejorado
- **QA interactivo en navegador (Playwright):** Acceso directo **Recortar** en la barra superior (`#cropToolBtn` / tecla `C`), encuadre automático completo al editar recortes o máscaras, sincronización de guías de composición, y sugerencia contextual dinámica (`#outputFormatHint`) al seleccionar el formato de salida.

---

## [2.8.0] — 2026-11-14

### Nuevo — Flujo completo de laboratorio (P1–P9)
- **80 emulsiones químicas y procesos de revelado (`Stand / Rodinal`, `Push +1/+2`, `Pull −1`).** Ocho películas contemporáneas/experimentales (`phoenix200`, `harman_switch`, `santacolor100`, `lomochrome92`, `metropolis400`, `lomo_purple`, `doublex5222`, `fomapan400`) y selector químico en `Emulación · 80`.
- **Sustratos atípicos sin máscara naranja + Visor de zona de cálculo / Sprockets.** Perfiles dedicados para Phoenix, Aerocolor IV, películas B&N transparentes y redscale/lomo, más guía superpuesta y conservación opcional de rebordes y perforaciones.
- **Calibración *Flat-Field* LED.** Neutraliza el viñeteo y la falta de uniformidad de la mesa de luz mediante toma de referencia vacía o mapa de ganancia.
- **Positivado B&N *Split Grade* y *Pre-flashing*.** Filtros grado `00` (luces) y grado `5` (sombras) más velo previo controlado.
- **Curva tonal compartida y Tira de prueba *f-stop*.** Editor de curvas disponible en ambos modos y generación rápida de tiras de 5 bandas en pasos de `1/3 EV` o `1/2 EV`.
- **Flujo rápido estilo Minilab + Vista Esencial.** Conmutador `Completa ↔ Esencial` (`V`) y atajos Fuji Frontier para exposición (`↑`/`↓`) y cabezal CMY (`C`, `G`, `B` + `⇧`).
- **Limpieza puntual de polvo/motas sin IR + Reciprocidad EXIF.** Clonado anular suave para emulsiones B&N, presets químicos rápidos y calculadora de fallo de reciprocidad Schwarzschild.
- **Marginador de cuarto oscuro (*Easel Borders*) y compensación *Dry-Down*.** Márgenes baritados, galería con filete o reborde negro de portanegativos y ajuste tonal de secado en exportación JPG, PNG y TIFF de 16 bits.

### Depuración y limpieza
- Eliminado por completo el código residual de «Máscaras de exposición» (`apply_local_exposure_offset` y comentarios CSS huérfanos).

---

## [2.6.0] — 2026-11-12

### Motor de imagen — Zonas tonales

- **Sombras, tonos medios y luces en el modo «Emulación · 72».** Nueva sección
  **«Zonas tonales»** en el inspector: reparte la exposición entre las tres
  regiones del rango tonal, como se reparte la luz en un cuarto oscuro.
- **Se aplican en luz lineal, antes de la respuesta de la emulsión**, así que un
  punto de EV es luz real y no un filtro de color.
- **Las zonas no se apilan.** Las tres máscaras suman exactamente el 100 %
  (partición de la unidad): subir sombras y medios a la vez produce un reparto
  ponderado, no la suma, y por eso no aparece el «barro» de los controles
  tonales que se solapan.
- **Cada zona tiene meseta.** Las sombras mandan en los negros profundos, los
  medios en el gris medio y las luces en las altas luces, con transiciones
  suaves. Las máscaras se calculan sobre la luminancia *perceptual*, no lineal.
- Coste en la previsualización: despreciable (~3 ms sobre ~240 ms de render).
- Cobertura completa: previsualización, exportación individual, lotes, hoja de
  contactos, revelado de rollo completo, receta por fotograma, copiar/pegar,
  sincronizar rollo, deshacer/rehacer, persistencia de preferencias e historial.
- **Inspector con scroll real.** Los paneles laterales son hijos flexibles de un
  contenedor con scroll: sin `flex-shrink: 0` podían comprimirse cuando no
  cabían y su contenido se desbordaba sobre el pie del inspector. Ahora
  mantienen su altura y el contenedor se desplaza.

---

## [2.5.1] — 2026-11-12

### Interfaz — Solapes en la barra del visor al maximizar la ventana

- **Los controles de la barra del visor se solapaban con la telemetría.** Al
  maximizar la ventana (por ejemplo, un MacBook Pro de 14" a 1512 px) el grupo de
  herramientas de geometría se encogía por debajo de su contenido y el botón
  «Sincronizar rollo» se montaba encima del distintivo «Original intacto», que
  además quedaba recortado en el borde. La causa era que los puntos de
  ruptura se medían contra el **ancho de la ventana** cuando la barra vive en la
  **columna central** (ventana − panel izquierdo − panel derecho).
- **La barra ahora se adapta a su propio ancho** mediante consultas de
  contenedor (`@container`), no a la pantalla: tres niveles de compactación
  progresiva (tipografía y etiqueta corta →Copiar/Pegar y «Ajustar» a icono →
 compactación máxima) que conservan siempre todas las funciones.
- **Nunca hay solapes ni controles recortados.** El grupo de geometría ya no se
  encoge por debajo de su contenido y la barra hace scroll horizontal como
  última red de seguridad. Verificado de 700 a 2560 px de ancho.
- **La telemetría se reubica en el densitómetro RGB** (junto a «Receta activa»):
  el estado de la edición no destructiva, la resolución y el tiempo de revelado
  quedan fuera de la fila de herramientas, donde ya no compiten por el espacio.
- **Compatibilidad con WebKit antiguo.** Los niveles de compactación se replican
  con consultas de medios bajo `@supports not (container-type: inline-size)`
  para macOS 11-12 (Safari 14-15), que no soporta consultas de contenedor.
- **Inspector del panel derecho aplastado en móvil.** Con la ventana muy
  estrecha el densitómetro comprimía el inspector a 26 px y sus controles se
  montaban sobre el botón de abajo; ahora los paneles se apilan y la página
  hace scroll.
- **Escalones de layout más coherentes:** panel izquierdo y derecho más estrechos
  en ventanas de 1120 px, y paso a la mesa de luz a una sola columna por debajo
  de 1024 px.

### Interfaz — Accesibilidad de teclado, contraste y zonas de pulsación

- **«Importar» era inalcanzable con el teclado.** El `<input type="file">` se
  ocultaba con `display: none`, así que la acción principal de la barra de
  herramientas quedaba fuera del recorrido de tabulación (sólo ratón o el atajo
  «O»). Ahora se oculta sólo visualmente y la etiqueta muestra el anillo de foco.
- **El anillo de foco se apagaba en los campos de formulario.** Las reglas
  `outline: none` de la búsqueda, los selectores EXIF, la hoja de contactos y la
  edición de valores apagaban también el indicador de teclado. Ahora sólo se
  desactiva con puntero (`:focus:not(:focus-visible)`).
- **Contraste corregido en el modo de luz roja.** El botón activo «Dividida»
  quedaba en rojo sobre rojo (ratio 1:1) por una regla meant para los botones
  ámbar. Verificado: cero textos por debajo de WCAG AA en ambos temas.
- **Nombres completos donde el texto se recorta:** el catálogo de películas y el
  rótulo del fotograma añaden tooltip con el nombre íntegro.
- **Zonas de pulsación ampliadas** sin cambiar el tamaño visual: clasificar,
  quitar fotograma y alternar el orden del catálogo.
- **La fecha del historial ya no se parte a mitad** de «2026-11-12 10:21:24».

### Empaquetado

- **Se publica la serie 2.5.1 para macOS** con los DMG de Apple Silicon y
  Intel rebuilt desde este mismo código:
  - `Haluro-2.5.1-macOS-arm64.dmg`
  - `Haluro-2.5.1-macOS-x86_64.dmg`
- **`rawpy` queda fijado a `<0.26`.** Es la última serie con ruedas macOS
  Intel: fijarlo permite que ambos DMG se construyan con **el mismo motor**
  (LibRaw) en lugar de dos versiones distintas según la arquitectura.
- La build Intel se genera con un CPython 3.12 x86_64 bajo Rosetta 2.

---

## [2.5.0] — 2026-11-12

### Seguridad — Sesión local protegida

- **Escritura arbitraria de ficheros corregida (path traversal).** Las claves de
  película y de perfil negativo se interpolaban sin verificar en las rutas de
  salida. Un parámetro con `../` escribía fuera de los directorios de la
  aplicación. Ahora se canonicalizan contra el catálogo y toda ruta se valida
  dentro de su directorio permitido.
- **DNS rebinding y POST desde sitios ajenos bloqueados.** El servidor ahora
  rechaza cualquier cabecera `Host` que no sea de loopback y cualquier
  `Origin` externo en las peticiones que modifican estado.
- **Token CSRF por proceso.** El frontend lo inyecta desde un `<meta>` que ya
  existía pero nunca se implementó, y el servidor lo exige en todos los
  `POST`/`PUT`/`PATCH`/`DELETE`.
- **Validación de entrada real.** Los parámetros numéricos se acotan a rangos
  utilizables; los valores no numéricos, no finitos o fuera de rango devuelven
  **HTTP 400** con un mensaje legible en lugar de un 500 genérico.
- **Subidas validadas por contenido.** Se comprueba que el fichero sea
  realmente una imagen decodificable, no solo que su extensión lo parezca.
- **Servidor de producción.** El backend pasa de Werkzeug a **Waitress**, sin
  *debugger* interactivo y con límites de conexión y de tiempo de espera.
- **CSP completada** con `object-src 'none'`, `base-uri 'none'`,
  `form-action 'self'` y `frame-src 'none'`.
- **Escrituras atómicas.** Toda exportación se escribe en un temporal y se mueve
  con `os.replace()`; una interrupción nunca deja un maestro truncado.

### Motor de imagen

- **TIFF de 16 bits corregido.** La escala se derivaba del *contenido* de la
  imagen en lugar de su profundidad declarada, de modo que un escaneo
  subexpuesto (por debajo de 255) se dividía por 255 en vez de por 65535: un
  error de **2.430×** que destruía la imagen antes de poder corregirla.
- **Grano determinista.** Se usaba el RNG global de NumPy: cada render sacaba
  un patrón distinto, la previsualización "hervía" al mover un control y el
  archivo exportado nunca coincidía con el aprobado. Ahora el grano se deriva
  de una semilla estable por fotograma y emulsión.
- **Transferencia Hurter–Driffield real.** El rango de densidad óptica medido se
  descartaba tras normalizar y la reconstrucción usaba una ley de potencia fija
  (`u ** 2.15`). Ahora la transferencia es exponencial en la densidad —como
  exige T = 10^(−D)— y el contraste medido del negativo determina la curva: un
  rollo empujado y uno plano ya no se reconstruyen igual.
- **Punto blanco corregido.** Se aplicaba un *roll-off* de Reinhard al espacio
  sRGB, que carece de hombro: el blanco puro salía en 247/255 en las 63
  películas del catálogo. `encode([1,1,1], "srgb")` ahora vale exactamente 1.0.
- **Halo del catálogo respetado.** El suelo `max(0.12, …)` anulaba el `glow`
  declarado: el perfil *Lineal* (0.0) recibía un halo 3× más fuerte del
  anunciado.
- **Redondeo correcto a 8 bits.** `astype(uint8)` truncaba y aplicaba un
  sesgo sistemático de −0,5 LSB a cada píxel exportado.

### Rendimiento y memoria

- La hoja de contactos reduce cada fotograma a miniatura **al cargarlo**; un
  rollo de 36 fotogramas de 24 MP consumía ~7 GB de RAM y provocaba la muerte
  del proceso por falta de memoria.
- Las conversiones de espacio de color ya no evaluan las dos ramas de `np.where`,
  lo que generaba 1,2 GB de arrays temporales por conversión de 24 MP.
- La caché LRU de imágenes lineales se limita a tamaños de previsualización y
  reduce su tamaño de 14 a 6 entradas.
- El revelado por lotes se acota a 200 fotogramas y a 2 desarrollos en paralelo
  a resolución completa.

### Interfaz y accesibilidad

- **La tecla `Tab` vuelve a recorrer la interfaz.** Estaba secuestrada para
  plegar los paneles laterales, lo que dejaba inalcanzables por teclado los 38
  controles, el catálogo de 72 películas y la barra de herramientas. El modo mesa
  limpia se mueve a `⌘/Ctrl + Alt + Z` y a su propio botón.
- El fondo de los modales se marca inerte mediante el atributo `inert`, con
  fallback para las versiones antiguas de WebKit que no implementan la
  propiedad IDL.
- El densitómetro del cursor se ejecuta una vez por fotograma de animación en
  lugar de en cada evento `mousemove`, con lectura de layout y `getImageData`
  por evento.
- El divisor de vista dividida ya no fuerza un *layout thrashing* en cada
  movimiento del puntero.
- La tira de fotogramas conserva la posición del desplazamiento al marcar o
  descartar una toma.
- El sondeo del revelado por lotes usa un temporizador recursivo con
  cancelación: antes, dos respuestas solapadas podían hacer retroceder la
  barra de progreso y un fallo de red dejaba el botón inutilizable.
- La detección automática de soporte (D-min) se descarta si el usuario cambió
  de fotograma mientras la petición estaba en vuelo.
- El estado de carga usa un contador, de modo que la superposición no desaparece antes
  de tiempo con operaciones concurrentes.
- El buscador de películas se debouncea: antes reconstruía las 72 tarjetas en cada
  pulsación.
- Las previsualizaciones se programan por control, de modo que mover dos
  controles seguidos no cancela el render del otro.

### Empaquetado e infraestructura

- **Versión única.** `engine/__init__.py` es la fuente de verdad; los scripts de
  macOS y Windows la resuelven en tiempo de compilación. La v2.4.6 publicó
  artefactos de Windows nombrados 2.4.5 y `version.json` apuntaba a una
  descarga inexistente.
- **CI multiplataforma real.** Se añade el trabajo de macOS (Apple Silicon e
  Intel) y un único trabajo de publicación que adjunta todos los artefactos.
- **Puerta de calidad en CI:** `ruff`, `pip-audit`, `pytest`, `--smoke-test` y
  el guardián de coherencia de versión.
- Las plantillas de Inno Setup y de metadatos PE se generan desde `*.in`.
- Rotación del registro (5 MB × 3) y poda de la carpeta de trabajo por
  antigüedad y por cuota.

### Documentación

- README y manual sincronizados con la versión; se documentan las protecciones
  reales de sesión, rutas y validación.
- Se aclara que los LUT incluidos son **CC BY-SA 4.0** y qué obligaciones
  impone una licencia *copyleft* sobre quien redistribuya una variante que
  los incruste.
- Se añaden 26 pruebas de regresión que reproducen cada defecto corregido.

[2.5.0]: https://github.com/Hermesuser/haluro/releases/tag/v2.5.0
