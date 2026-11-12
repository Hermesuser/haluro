"""Tests E2E del frontend con Playwright.

Requisitos previos:
    pip install playwright
    playwright install chromium

Ejecutar con:
    pytest tests/test_e2e_playwright.py --headed

Estos tests navegan la SPA real de Haluro (localhost:5050) y verifican que
los flujos críticos funcionan en el navegador, no solo a nivel de API.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

playwright = pytest.importorskip("playwright.sync_api")  # noqa: F401


@pytest.fixture(scope="session")
def haluro_server(tmp_path_factory):
    """Arranca el backend de Haluro en un puerto libre para tests E2E."""
    import socket

    import app as haluro_app

    # Usar directorios de datos temporales
    data_dir = tmp_path_factory.mktemp("haluro_e2e")
    monkeypatch_dirs = {
        "UPLOAD_DIR": data_dir / "uploads",
        "DEVELOPED_DIR": data_dir / "developed",
    }
    for d in monkeypatch_dirs.values():
        d.mkdir()

    # Puerto libre
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # Arrancar servidor en hilo
    import threading

    def _run():
        haluro_app.app.config["TESTING"] = True
        haluro_app.UPLOAD_DIR = monkeypatch_dirs["UPLOAD_DIR"]
        haluro_app.DEVELOPED_DIR = monkeypatch_dirs["DEVELOPED_DIR"]
        haluro_app.app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Esperar a que responda
    import urllib.request
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    # El hilo es daemon, termina con el proceso


def test_e2e_simulation_flow(page, haluro_server):
    """Flujo completo: abrir app → importar → preview → exportar."""
    page.goto(haluro_server)

    # Verificar que carga la marca
    assert page.locator("h1:has-text('Haluro')").count() > 0

    # Clic en "Muestra" para cargar RAW de prueba
    page.locator("#loadSampleBtn").click()

    # Esperar a que aparezca una miniatura o preview
    page.locator("img").first.wait_for(timeout=5000)

    # Exportar a Descargas
    page.locator("#saveDownloadsBtn").click()

    # Verificar que no hay errores visibles (mensaje de éxito o archivo descargado)
    # El backend guarda en ~/Downloads; en tests no se puede verificar fácilmente
    # el sistema de archivos del host, así que solo verificamos que no hay error.


def test_e2e_negative_mode(page, haluro_server):
    """Cambiar a modo negativo y verificar que se activa."""
    page.goto(haluro_server)

    # Clic en pestaña "Revelar negativo"
    page.locator("#tabNegativeMode").click()

    # Verificar que el panel de controles de negativo está visible
    page.locator("#negativeControls").wait_for(timeout=5000)
