# Changelog

Todas las versiones relevantes de Haluro se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y
el proyecto usa [versionado semántico](https://semver.org/lang/es/).

La versión vive en un único sitio: `engine/__init__.py`. Un guardián en la CI
(`.github/scripts/check_version.py`) verifica que ninguna otra copia se desvíe.

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
