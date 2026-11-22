"""Tests for Phase 2 features: source EXIF, gallery_caption, export_max_dim, prefetch, CLI render-project."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.pipeline import extract_source_exif, save_output_image


def test_extract_source_exif_reads_camera_and_exposure(tmp_path: Path) -> None:
    """extract_source_exif parses Make, Model, and builds a readable summary."""
    jpg_path = tmp_path / "exif_sample.jpg"
    img = Image.new("RGB", (64, 48), (120, 100, 80))
    exif = img.getexif()
    exif[271] = "Nikon"
    exif[272] = "Nikon FM2"
    img.save(jpg_path, format="JPEG", exif=exif)

    info = extract_source_exif(jpg_path)
    assert info["camera"] == "Nikon FM2"
    assert "Nikon FM2" in info["summary"]


def test_gallery_caption_border_and_export_max_dim(tmp_path: Path) -> None:
    """save_output_image downscales to export_max_dim and adds gallery_caption border cleanly."""
    img = Image.new("RGB", (400, 200), (80, 120, 160))
    out_path = tmp_path / "gallery_web.jpg"
    res = save_output_image(
        img,
        out_path,
        quality=85,
        easel_border="gallery_caption",
        analog_meta={"camera": "Leica M6", "film_stock": "Kodak Portra 400", "shot_iso": "400"},
        export_max_dim=200,
    )
    assert out_path.is_file()
    # Base image was scaled to 200x100, then gallery_caption border padded it
    assert res.width > 200 and res.width < 320
    assert res.height > 100 and res.height < 220


def test_prefetch_endpoint_and_cli_render_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """POST /api/prefetch warms thumbnails and cli.py render-project renders a .haluro archive."""
    import app as haluro_app

    uploads = tmp_path / "uploads"
    projects = tmp_path / "projects"
    uploads.mkdir()
    projects.mkdir()
    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "PROJECTS_DIR", projects.resolve())
    haluro_app.app.config["TESTING"] = True

    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (140, 110, 90)).save(buf, format="JPEG")
    buf.seek(0)

    with haluro_app.app.test_client() as client:
        headers = {"X-Haluro-Token": haluro_app.API_TOKEN}
        up = client.post(
            "/api/upload",
            data={"file": (buf, "cli_roll_01.jpg")},
            content_type="multipart/form-data",
            headers=headers,
        )
        assert up.status_code == 200
        fname = up.get_json()["filename"]

        # Prefetch warms cache cleanly
        pf = client.post("/api/prefetch", json={"filenames": [fname]}, headers=headers)
        assert pf.status_code == 200
        assert pf.get_json()["warmed"] == 1

        # Save & export a .haluro project
        save_r = client.post(
            "/api/projects",
            json={
                "name": "CLI Roll Test",
                "app_mode": "simulation",
                "frames": [
                    {
                        "filename": fname,
                        "name": "cli_roll_01.jpg",
                        "pickStatus": "pick",
                        "simRecipe": {"film": "hp5", "bw_filter": "yellow", "film_strength": 0.9},
                    }
                ],
            },
            headers=headers,
        )
        assert save_r.status_code == 200
        pid = save_r.get_json()["project"]["id"]

        exp_r = client.get(f"/api/projects/{pid}/export")
        assert exp_r.status_code == 200
        haluro_file = tmp_path / "cli_roll.haluro"
        haluro_file.write_bytes(exp_r.data)

    # Render the exported .haluro archive via CLI
    cli_out = tmp_path / "cli_output"
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "cli.py"),
            "render-project",
            str(haluro_file),
            "--out",
            str(cli_out),
            "--only-picked",
            "--max-dim",
            "64",
            "--sheet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    rendered = list(cli_out.glob("01_*.jpg"))
    assert len(rendered) == 1
    assert (cli_out / "SHEET_PROJECT.jpg").is_file()


def test_storage_info_and_safe_cache_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """GET /api/storage reports sizes and POST /api/storage/clean spares protected project uploads."""
    import app as haluro_app

    uploads = tmp_path / "uploads"
    developed = tmp_path / "developed"
    projects = tmp_path / "projects"
    for d in (uploads, developed, projects):
        d.mkdir()
    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "DEVELOPED_DIR", developed.resolve())
    monkeypatch.setattr(haluro_app, "PROJECTS_DIR", projects.resolve())
    haluro_app.app.config["TESTING"] = True

    def _jpeg_bytes() -> io.BytesIO:
        b = io.BytesIO()
        Image.new("RGB", (40, 40), (100, 120, 140)).save(b, format="JPEG")
        b.seek(0)
        return b

    with haluro_app.app.test_client() as client:
        headers = {"X-Haluro-Token": haluro_app.API_TOKEN}
        f_keep = client.post(
            "/api/upload",
            data={"file": (_jpeg_bytes(), "keep_in_proj.jpg")},
            content_type="multipart/form-data",
            headers=headers,
        ).get_json()["filename"]
        f_drop = client.post(
            "/api/upload",
            data={"file": (_jpeg_bytes(), "temp_unused.jpg")},
            content_type="multipart/form-data",
            headers=headers,
        ).get_json()["filename"]

        # Protect f_keep in a saved project
        assert client.post(
            "/api/projects",
            json={"name": "Safe Roll", "frames": [{"filename": f_keep, "name": f_keep}]},
            headers=headers,
        ).status_code == 200

        st = client.get("/api/storage").get_json()["storage"]
        assert st["uploads"]["files"] == 2
        assert st["total_bytes"] > 0

        # Clean uploads: f_drop removed, f_keep spared
        cl = client.post("/api/storage/clean", json={"target": "uploads"}, headers=headers)
        assert cl.status_code == 200
        assert cl.get_json()["removed_files"] == 1
        assert (uploads / f_keep).is_file()
        assert not (uploads / f_drop).exists()
