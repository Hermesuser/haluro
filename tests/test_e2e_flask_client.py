"""Tests de integración (E2E lite) sobre el cliente de Flask.

Cubren flujos críticos de usuario sin necesidad de un navegador real:
importar muestra → generar preview → exportar a disco → consultar historial.

Se ejecutan con el cliente de pruebas de Flask y requieren `pytest` y las
dependencias de runtime de Haluro (Pillow, rawpy, numpy, etc.).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app as haluro_app

    uploads = tmp_path / "uploads"
    developed = tmp_path / "developed"
    downloads = tmp_path / "Downloads"
    for folder in (uploads, developed, downloads):
        folder.mkdir()

    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "DEVELOPED_DIR", developed.resolve())
    monkeypatch.setattr(haluro_app, "get_downloads_dir", lambda: downloads.resolve())
    monkeypatch.setattr(haluro_app, "reveal_in_file_manager", lambda _p: True)
    monkeypatch.setattr(
        haluro_app,
        "EXPORT_ALLOWED_ROOTS",
        (developed.resolve(), downloads.resolve(), tmp_path.resolve()),
    )

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as test_client:
        test_client.environ_base["HTTP_X_HALURO_TOKEN"] = haluro_app.API_TOKEN
        yield test_client


def _make_jpeg(name: str = "test.jpg") -> tuple[str, io.BytesIO]:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 60, 90)).save(buf, format="JPEG")
    buf.seek(0)
    return name, buf


# ---------------------------------------------------------------------------
# Flujo 1: Simulación (emulación de película)
# ---------------------------------------------------------------------------

def test_simulation_flow_preview_and_export(client, tmp_path: Path) -> None:
    """Importar → preview → exportar un frame en modo simulación."""

    # 1. Cargar una imagen de prueba
    name, buf = _make_jpeg("foto_prueba.jpg")
    resp = client.post(
        "/api/upload",
        data={"file": (buf, name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    upload_data = resp.get_json()
    assert upload_data["filename"] == "foto_prueba.jpg"

    # 2. Generar preview de simulación
    resp = client.post(
        "/api/preview",
        json={
            "filename": "foto_prueba.jpg",
            "film": "portra400",
            "ev": 0.0,
            "halation": 1.0,
            "grain": 1.0,
            "vignette": 1.0,
            "include_original": True,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    prev = resp.get_json()
    assert prev["developed"].startswith("data:image/jpeg;base64,")
    assert prev["original"].startswith("data:image/jpeg;base64,")
    assert prev["width"] > 0 and prev["height"] > 0

    # 3. Exportar a resolución completa
    resp = client.post(
        "/api/export_single",
        json={
            "filename": "foto_prueba.jpg",
            "film": "portra400",
            "format": "jpg",
            "ev": 0.0,
            "halation": 1.0,
            "grain": 1.0,
            "vignette": 1.0,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    export = resp.get_json()
    assert export["success"] is True
    assert Path(export["path"]).is_file()

    # 4. El historial debe contener la exportación
    resp = client.get("/api/history")
    assert resp.status_code == 200
    history = resp.get_json()["history"]
    assert any(h["filename"] == Path(export["path"]).name for h in history)


# ---------------------------------------------------------------------------
# Flujo 2: Negativo (inversión óptica)
# ---------------------------------------------------------------------------

def test_negative_flow_preview_and_export(client, tmp_path: Path) -> None:
    """Importar → preview → exportar un negativo en modo inversión óptica."""

    # 1. Cargar una imagen de prueba (simula un escaneo de negativo)
    name, buf = _make_jpeg("negativo_prueba.jpg")
    resp = client.post(
        "/api/upload",
        data={"file": (buf, name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # 2. Generar preview de inversión
    resp = client.post(
        "/api/negative/preview",
        json={
            "filename": "negativo_prueba.jpg",
            "profile": "frontier",
            "film_type": "color",
            "light_source": "standard",
            "scan_source": "camera_raw",
            "color_method": "dynamic",
            "include_original": True,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    prev = resp.get_json()
    assert prev["developed"].startswith("data:image/jpeg;base64,")
    assert prev["width"] > 0 and prev["height"] > 0

    # 3. Exportar a resolución completa
    resp = client.post(
        "/api/negative/save_to_downloads",
        json={
            "filename": "negativo_prueba.jpg",
            "profile": "frontier",
            "format": "jpg",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    export = resp.get_json()
    assert export["success"] is True
    assert Path(export["saved_path"]).is_file()


# ---------------------------------------------------------------------------
# Flujo 3: Catálogo de películas y salud
# ---------------------------------------------------------------------------

def test_films_and_health(client) -> None:
    """El catálogo debe devolver 72 películas y /api/health debe estar OK."""
    resp = client.get("/api/films")
    assert resp.status_code == 200
    films = resp.get_json()["films"]
    assert len(films) == 72, f"Se esperaban 72 películas, se obtuvieron {len(films)}"

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["films_count"] == 72


# ---------------------------------------------------------------------------
# Flujo 4: Subida de archivo inválido debe rechazarse
# ---------------------------------------------------------------------------

def test_upload_rejects_non_image(client) -> None:
    """Un archivo que no es imagen debe ser rechazado con 400."""
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"not an image"), "fake.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
