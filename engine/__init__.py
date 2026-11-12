"""Haluro optical color & sensitometric processing engine.

Single source of truth for product identity, authorship and licensing metadata.
Consumed by the Flask backend (`/api/about`), the native launcher, the CLI
(`--version` / `about`), and the macOS / Windows 11 packaging scripts.

This module is also the **single source of truth for the version number**: the
packaging pipelines read `__version__` from here instead of carrying their own
hardcoded copy, which previously drifted (the Windows build kept shipping 2.4.5
artefacts for a 2.4.6 release).
"""

__version__ = "2.5.0"
APP_NAME = "Haluro"
APP_FULL_NAME = "Haluro — Laboratorio Analógico Digital"
APP_TAGLINE = (
    "Emulación de 72 películas químicas y revelado digital de negativos escaneados, "
    "con edición 100% no destructiva."
)
APP_BUNDLE_ID = "studio.haluro.lab"
APP_COPYRIGHT_YEAR = "2026"

DEVELOPER = {
    "name": "César Fernández Ardiles",
    "role": "Fotógrafo y desarrollador",
    "studio": "Oregano",
    "country": "Chile",
}

__author__ = DEVELOPER["name"]
__license__ = "MIT"
__copyright__ = (
    f"Copyright (c) {APP_COPYRIGHT_YEAR} {DEVELOPER['name']} "
    f"· {DEVELOPER['studio']} · {DEVELOPER['country']}"
)

# Credits for bundled third-party assets & runtime components (see THIRD_PARTY_NOTICES.md).
THIRD_PARTY_CREDITS = (
    {
        "component": "Colección de simulación de película (LUT 3D .cube)",
        "author": "Pat David, Pavlov Dmitry, Michael Ezra et al. (RawTherapee / G'MIC)",
        "license": "CC BY-SA 4.0",
    },
    {"component": "Plus Jakarta Sans", "author": "The Plus Jakarta Sans Project Authors", "license": "SIL OFL 1.1"},
    {"component": "JetBrains Mono", "author": "The JetBrains Mono Project Authors", "license": "SIL OFL 1.1"},
    {"component": "LibRaw (vía rawpy)", "author": "LibRaw LLC", "license": "LGPL 2.1 / CDDL 1.0"},
    {"component": "rawpy", "author": "Maik Riechert", "license": "MIT"},
    {"component": "Flask · Werkzeug · Jinja2", "author": "Pallets", "license": "BSD-3-Clause"},
    {"component": "NumPy · SciPy", "author": "NumPy & SciPy Developers", "license": "BSD-3-Clause"},
    {"component": "Pillow", "author": "Jeffrey A. Clark and contributors", "license": "MIT-CMU (HPND)"},
    {"component": "pywebview", "author": "Roman Sirokov and contributors", "license": "BSD-3-Clause"},
    {"component": "Python", "author": "Python Software Foundation", "license": "PSF-2.0"},
)

TRADEMARK_NOTICE = (
    "Kodak, Fujifilm, Ilford, Agfa, CineStill, Rollei, Lomography, Polaroid, Noritsu, Frontier, "
    "Foma y demás nombres de películas, papeles o equipos son marcas de sus respectivos titulares. "
    "Se citan solo para describir la estética que cada perfil aproxima; Haluro no está afiliado, "
    "patrocinado ni respaldado por ninguno de ellos."
)

PRIVACY_NOTICE = (
    "Haluro funciona 100% en tu equipo: no envía fotografías, metadatos ni telemetría a Internet. "
    "Los archivos originales nunca se modifican."
)


def about_payload() -> dict:
    """Return a JSON-serializable product, authorship and licensing summary."""
    return {
        "app": APP_NAME,
        "full_name": APP_FULL_NAME,
        "tagline": APP_TAGLINE,
        "version": __version__,
        "bundle_id": APP_BUNDLE_ID,
        "copyright": __copyright__,
        "license": __license__,
        "developer": dict(DEVELOPER),
        "third_party": [dict(item) for item in THIRD_PARTY_CREDITS],
        "trademark_notice": TRADEMARK_NOTICE,
        "privacy_notice": PRIVACY_NOTICE,
    }
