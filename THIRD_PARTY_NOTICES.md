# Avisos de Terceros y Licencias de Componentes (Third-Party Notices)

Haluro — Laboratorio Analógico Digital incluye código, tablas de color y tipografías desarrolladas por la comunidad de software libre. Este documento detalla las licencias y atribuciones correspondientes para garantizar el estricto cumplimiento del derecho de autor y la distribución gratuita sin restricciones.

---

## 1. Tablas de Consulta de Color 3D (3D CLUTs / HaldCLUT)

- **Ubicación en el repositorio:** `luts/` (`luts/bw`, `luts/colorslide`, `luts/negative_color`, `luts/negative_new`, `luts/negative_old`, `luts/print`).
- **Autores y colaboradores:** Pat David (PIXLS.US), Pavlov Dmitry, Michael Ezra, David Tschumperlé y la comunidad de G'MIC / RawTherapee.
- **Licencia:** [Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/).
- **Atribución:** Las matrices 3D `.cube` de simulación de emulsión fueron convertidas a partir de la colección libre de simulación de película de código abierto compilada por Pat David y GREYC/G'MIC.
- **Términos de redistribución:** Se distribuyen bajo los términos de la licencia CC BY-SA 4.0. Haluro permite su uso, estudio y modificación citando la autoría original.

---

## 2. Tipografías Autónomas (Self-Hosted Web Fonts)

Haluro aloja sus tipografías localmente en `static/fonts/` para operar al 100% sin conexión a Internet (cero peticiones externas hacia servidores de Google o terceros).

### Plus Jakarta Sans
- **Ubicación:** `static/fonts/PlusJakartaSans-*.woff2`
- **Copyright:** Copyright 2020 The Plus Jakarta Sans Project Authors (https://github.com/tokotype/PlusJakartaSans)
- **Licencia:** SIL Open Font License, Versión 1.1 (`static/fonts/OFL-PlusJakartaSans.txt`).

### JetBrains Mono
- **Ubicación:** `static/fonts/JetBrainsMono-*.woff2`
- **Copyright:** Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)
- **Licencia:** SIL Open Font License, Versión 1.1 (`static/fonts/OFL-JetBrainsMono.txt`).

---

## 3. Dependencias de Ejecución (Python Runtime)

| Paquete | Titular / Autor | Licencia | Uso en Haluro |
| :--- | :--- | :--- | :--- |
| **Flask** | Pallets Projects | BSD-3-Clause | Servidor de aplicación local (`127.0.0.1`) |
| **Werkzeug** | Pallets Projects | BSD-3-Clause | Manejo HTTP y utilidades seguras (`secure_filename`) |
| **NumPy** | NumPy Developers | BSD-3-Clause | Operaciones matriciales y espacios de color |
| **SciPy** | SciPy Developers | BSD-3-Clause | Filtros gaussianos y convolución para halo y grano |
| **Pillow** | Jeffrey A. Clark & contribuyentes | MIT-CMU (HPND) | E/S de imagen, EXIF nativo y metadatos |
| **rawpy / LibRaw** | Maik Riechert / LibRaw LLC | MIT / LGPL-2.1 / CDDL-1.0 | Decodificación nativa de RAW analógico-digital (16-bit) |
| **pywebview** | Roman Sirokov | BSD-3-Clause | Ventana nativa de escritorio (Cocoa WebKit / Edge WebView2) |

---

## 4. Cláusula de Marcas Registradas (Nominative Fair Use)

Los nombres de marcas comerciales, tales como **Kodak**, **Fujifilm**, **Ilford**, **Agfa**, **CineStill**, **Rollei**, **Lomography**, **Polaroid**, **Noritsu**, **Frontier**, **Foma**, **Hasselblad**, **Adobe**, **Lightroom** y **Photoshop**, se mencionan exclusivamente con fines descriptivos e informativos para identificar las emulsiones, papeles fotográficos y equipos de laboratorio analógico que los modelos matemáticos y filtros de Haluro aproximan.

- Haluro es un proyecto independiente desarrollado por el **Fotógrafo César Fernández Ardiles (Oregano, Chile)**.
- Haluro **no** está afiliado, patrocinado, respaldado ni asociado formalmente con ninguna de las empresas titulares de dichas marcas comerciales.
- Todas las marcas pertenecen a sus respectivos propietarios legales.

---

## 5. Privacidad y Seguridad del Usuario

1. **Operación Local Estricta:** Haluro se ejecuta enteramente en el equipo del usuario a través de la interfaz de loopback local (`127.0.0.1`). No transfiere fotografías, escaneos ni recetas a la nube ni a ningún servidor remoto.
2. **Edición 100% No Destructiva:** Los archivos originales cargados (archivos RAW de cámara, TIFF o JPEG) nunca se modifican, sobrescriben ni eliminan.
3. **Cero Telemetría:** La aplicación no incluye códigos de seguimiento, publicidad ni recopilación de datos analíticos.
