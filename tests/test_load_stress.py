"""Tests de carga y estrés para Haluro.

Verifican que el procesamiento por lotes de muchas imágenes grandes no agote
la memoria ni falle con errores internos. Se ejecutan con el cliente de pruebas
de Flask y generan imágenes sintéticas en disco temporal.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
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


def _make_large_jpeg(path: Path, width: int = 2400, height: int = 1600) -> str:
    """Genera una imagen sintética grande (simula un escaneo de 24 MP)."""
    arr = np.random.default_rng(42).integers(
        0, 255, size=(height, width, 3), dtype=np.uint8
    )
    Image.fromarray(arr, mode="RGB").save(path, format="JPEG", quality=90)
    return path.name


# ---------------------------------------------------------------------------
# Estrés: lote grande de frames full-res (síncrono vía develop_full)
# ---------------------------------------------------------------------------

def test_develop_full_handles_many_frames(client, tmp_path: Path) -> None:
    """Procesar 20 frames de 6 MP vía develop_full no debe fallar."""
    filenames = []
    for i in range(20):
        name = f"frame_{i:02d}.jpg"
        path = tmp_path / "uploads" / name
        _make_large_jpeg(path, width=2000, height=1333)
        filenames.append(name)

    resp = client.post(
        "/api/develop_full",
        json={
            "filenames": filenames,
            "film": "portra400",
            "ev": 0.0,
            "halation": 1.0,
            "grain": 1.0,
            "vignette": 1.0,
            "sheet": False,
            "format": "jpg",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_frames"] == 20
    assert len(data["files"]) == 20


# ---------------------------------------------------------------------------
# Estrés: roll batch worker directo (sin HTTP)
# ---------------------------------------------------------------------------

def test_roll_batch_job_completes_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RollBatchJob.run() debe completar un lote de 10 frames sin errores."""
    import app as haluro_app
    from engine.roll_processor import RollBatchJob

    uploads = tmp_path / "uploads"
    developed = tmp_path / "developed"
    downloads = tmp_path / "Downloads"
    for folder in (uploads, developed, downloads):
        folder.mkdir()

    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "DEVELOPED_DIR", developed.resolve())
    monkeypatch.setattr(haluro_app, "get_downloads_dir", lambda: downloads.resolve())
    monkeypatch.setattr(haluro_app, "reveal_in_file_manager", lambda _p: True)

    # Crear 10 frames sintéticos
    filenames = []
    for i in range(10):
        name = f"direct_frame_{i:02d}.jpg"
        path = uploads / name
        _make_large_jpeg(path, width=1500, height=1000)
        filenames.append(name)

    data = {
        "filenames": filenames,
        "app_mode": "simulation",
        "film": "portra400",
        "ev": 0.0,
        "halation": 1.0,
        "grain": 1.0,
        "vignette": 1.0,
        "sheet": True,
        "format": "jpg",
        "roll_name": "Stress Test Roll",
        "columns": 4,
    }

    job = RollBatchJob("stress-test-001", data)
    job.run()

    assert job.status == "completed", f"Job falló: {job.error}"
    assert job.result is not None
    assert job.result["total_frames"] == 10
    assert job.result["sheet"] is True
    assert len(job.result["files"]) == 11  # 10 frames + 1 sheet


# ---------------------------------------------------------------------------
# Estrés: preview repetido sin fugas de caché
# ---------------------------------------------------------------------------

def test_repeated_previews_do_not_exhaust_cache(client, tmp_path: Path) -> None:
    """Múltiples previews con distintos parámetros no deben saturar la caché."""
    name = _make_large_jpeg(tmp_path / "uploads" / "stress.jpg", width=1200, height=800)

    for i in range(20):
        resp = client.post(
            "/api/preview",
            json={
                "filename": name,
                "film": "portra400",
                "ev": i * 0.1,
                "halation": 1.0,
                "grain": 1.0,
                "vignette": 1.0,
                "include_original": False,
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["developed"].startswith("data:image/jpeg;base64,")
