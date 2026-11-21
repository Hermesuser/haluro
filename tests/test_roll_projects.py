"""Tests for persistent digital roll projects (save, list, load, update, delete, security)."""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app as haluro_app

    uploads = tmp_path / "uploads"
    developed = tmp_path / "developed"
    projects = tmp_path / "projects"
    downloads = tmp_path / "Downloads"
    for folder in (uploads, developed, projects, downloads):
        folder.mkdir()

    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "DEVELOPED_DIR", developed.resolve())
    monkeypatch.setattr(haluro_app, "PROJECTS_DIR", projects.resolve())
    monkeypatch.setattr(haluro_app, "get_downloads_dir", lambda: downloads.resolve())
    monkeypatch.setattr(haluro_app, "reveal_in_file_manager", lambda _p: True)

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as test_client:
        test_client.environ_base["HTTP_X_HALURO_TOKEN"] = haluro_app.API_TOKEN
        yield test_client, uploads, projects


def _make_jpeg(color: tuple[int, int, int] = (120, 80, 60)) -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    buf.seek(0)
    return buf


def _upload(test_client, name: str, color: tuple[int, int, int] = (120, 80, 60)) -> str:
    resp = test_client.post(
        "/api/upload",
        data={"file": (_make_jpeg(color), name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["filename"]


def test_save_list_load_and_restore_after_upload_wipe(client) -> None:
    """Saving a roll project protects its images and restores every per-frame recipe."""
    test_client, uploads, projects = client
    f1 = _upload(test_client, "frame_01.jpg", (200, 100, 50))
    f2 = _upload(test_client, "frame_02.jpg", (50, 140, 210))

    payload = {
        "name": "Valparaíso Portra 400",
        "notes": "Nikon FM2 · 50mm f/1.4",
        "app_mode": "simulation",
        "active_frame_index": 1,
        "view_mode": "full",
        "sheet": {"roll_name": "VALPO 01", "columns": 5, "hide_rejected": True},
        "export": {"output_format": "tiff", "easel_border": "thin_white", "dry_down_comp": 0.15},
        "analog_meta": {"camera": "Nikon FM2", "lens": "50mm f/1.4", "film_stock": "Kodak Portra 400"},
        "frames": [
            {
                "filename": f1,
                "name": "frame_01.jpg",
                "is_raw": False,
                "is_sample": False,
                "pickStatus": "pick",
                "simRecipe": {"film": "portra400", "ev": 0.35, "grain": 1.2, "halation": 0.8},
            },
            {
                "filename": f2,
                "name": "frame_02.jpg",
                "is_raw": False,
                "is_sample": False,
                "pickStatus": "reject",
                "simRecipe": {"film": "hp5", "ev": -0.25, "grain": 1.5, "rotate": 90},
            },
        ],
    }

    # 1. Save project
    resp = test_client.post("/api/projects", json=payload)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    saved = resp.get_json()
    assert saved["success"] is True
    assert saved["missing_files"] == []
    pid = saved["project"]["id"]
    assert saved["project"]["name"] == "Valparaíso Portra 400"
    assert saved["project"]["frame_count"] == 2
    assert saved["project"]["picked_count"] == 1
    assert saved["project"]["rejected_count"] == 1
    assert saved["project"]["edited_count"] == 2

    # 2. List projects & fetch cover thumbnail
    list_resp = test_client.get("/api/projects")
    assert list_resp.status_code == 200
    items = list_resp.get_json()["projects"]
    assert len(items) == 1
    assert items[0]["id"] == pid

    thumb_resp = test_client.get(f"/api/projects/{pid}/thumb")
    assert thumb_resp.status_code == 200
    assert thumb_resp.mimetype == "image/jpeg"
    assert len(thumb_resp.data) > 100

    # 3. Simulate uploads directory being cleaned up later
    (uploads / f1).unlink()
    (uploads / f2).unlink()
    assert not (uploads / f1).exists()
    assert not (uploads / f2).exists()

    # 4. Load project — must restore files into uploads/ and preserve all recipes
    load_resp = test_client.get(f"/api/projects/{pid}")
    assert load_resp.status_code == 200, load_resp.get_data(as_text=True)
    loaded = load_resp.get_json()
    assert loaded["missing_files"] == []
    proj = loaded["project"]
    assert proj["name"] == "Valparaíso Portra 400"
    assert proj["active_frame_index"] == 1
    assert proj["sheet"]["roll_name"] == "VALPO 01"
    assert proj["sheet"]["columns"] == 5
    assert proj["export"]["output_format"] == "tiff"
    assert proj["analog_meta"]["camera"] == "Nikon FM2"
    assert len(proj["frames"]) == 2
    assert proj["frames"][0]["pickStatus"] == "pick"
    assert proj["frames"][0]["simRecipe"]["film"] == "portra400"
    assert proj["frames"][0]["simRecipe"]["ev"] == pytest.approx(0.35)
    assert proj["frames"][1]["simRecipe"]["film"] == "hp5"
    assert proj["frames"][1]["simRecipe"]["rotate"] == 90

    # Restored files exist in uploads/ again and can generate previews
    assert (uploads / f1).is_file()
    assert (uploads / f2).is_file()


def test_update_project_cleans_removed_media_and_preserves_created_at(client) -> None:
    """Updating an existing project removes orphaned media and keeps created_at."""
    test_client, _uploads, projects = client
    f1 = _upload(test_client, "keep.jpg")
    f2 = _upload(test_client, "drop.jpg")

    resp = test_client.post(
        "/api/projects",
        json={
            "name": "Rollo inicial",
            "app_mode": "simulation",
            "frames": [
                {"filename": f1, "name": "keep.jpg", "simRecipe": {"film": "gold200"}},
                {"filename": f2, "name": "drop.jpg", "simRecipe": {"film": "gold200"}},
            ],
        },
    )
    assert resp.status_code == 200
    first = resp.get_json()["project"]
    pid = first["id"]
    media_dir = projects / pid / "media"
    assert (media_dir / f1).is_file()
    assert (media_dir / f2).is_file()

    # Update project removing f2
    upd = test_client.post(
        "/api/projects",
        json={
            "project_id": pid,
            "name": "Rollo depurado",
            "app_mode": "simulation",
            "frames": [
                {"filename": f1, "name": "keep.jpg", "simRecipe": {"film": "velvia50"}},
            ],
        },
    )
    assert upd.status_code == 200
    second = upd.get_json()["project"]
    assert second["id"] == pid
    assert second["name"] == "Rollo depurado"
    assert second["created_at"] == first["created_at"]
    assert second["frame_count"] == 1
    assert (media_dir / f1).is_file()
    assert not (media_dir / f2).exists()


def test_rename_delete_and_prune_protection(client) -> None:
    """Renaming, deleting, and workspace prune protection work as expected."""
    import app as haluro_app

    test_client, uploads, _projects = client
    f1 = _upload(test_client, "protected.jpg")
    f_stale = _upload(test_client, "stale_unreferenced.jpg")

    # Age both files past UPLOAD_RETENTION_DAYS
    old_time = time.time() - ((haluro_app.UPLOAD_RETENTION_DAYS + 5) * 86400)
    os.utime(uploads / f1, (old_time, old_time))
    os.utime(uploads / f_stale, (old_time, old_time))

    resp = test_client.post(
        "/api/projects",
        json={
            "name": "Proyecto Protegido",
            "app_mode": "negative",
            "negative_roll": {
                "roll_bounds": {"d_min": [0.1, 0.2, 0.3], "d_max": [2.0, 2.1, 2.2]},
                "roll_frames_count": 1,
            },
            "frames": [{"filename": f1, "name": "protected.jpg", "negRecipe": {"profile": "noritsu"}}],
        },
    )
    assert resp.status_code == 200
    pid = resp.get_json()["project"]["id"]

    # Prune workspace: protected file stays, stale unreferenced file is pruned
    haluro_app._prune_workspace()
    assert (uploads / f1).is_file()
    assert not (uploads / f_stale).exists()

    # Rename project
    ren = test_client.patch(f"/api/projects/{pid}", json={"name": "Proyecto Renombrado", "notes": "Actualizado"})
    assert ren.status_code == 200
    assert ren.get_json()["project"]["name"] == "Proyecto Renombrado"
    assert ren.get_json()["project"]["notes"] == "Actualizado"

    # Delete project
    dele = test_client.delete(f"/api/projects/{pid}")
    assert dele.status_code == 200
    assert test_client.get(f"/api/projects/{pid}").status_code == 404


def test_project_security_and_validation(client) -> None:
    """Rejects path traversal in project_id, empty rolls, and missing CSRF tokens."""
    test_client, _uploads, _projects = client

    # Empty frames rejected
    assert test_client.post("/api/projects", json={"name": "Vacío", "frames": []}).status_code == 400

    # Invalid project_id rejected
    assert test_client.get("/api/projects/..%2Fetc%2Fpasswd").status_code in (400, 404)
    assert test_client.post(
        "/api/projects",
        json={"project_id": "../../escape", "name": "Bad", "frames": [{"filename": "x.jpg"}]},
    ).status_code == 400

    # Missing X-Haluro-Token rejected on POST
    import app as haluro_app

    with haluro_app.app.test_client() as unauth_client:
        resp = unauth_client.post("/api/projects", json={"name": "NoToken", "frames": [{"filename": "x.jpg"}]})
        assert resp.status_code == 403


def test_export_and_import_portable_haluro_archive(client) -> None:
    """Exporting a project to .haluro and importing it back restores all frames and recipes."""
    import zipfile

    test_client, uploads, _projects = client
    f1 = _upload(test_client, "portable_01.jpg", (90, 180, 120))

    resp = test_client.post(
        "/api/projects",
        json={
            "name": "Archivo Portable",
            "notes": "Para respaldo externo",
            "app_mode": "simulation",
            "frames": [
                {
                    "filename": f1,
                    "name": "portable_01.jpg",
                    "pickStatus": "pick",
                    "simRecipe": {"film": "cinestill800t", "ev": 0.5, "halation": 1.4},
                }
            ],
        },
    )
    assert resp.status_code == 200
    orig_pid = resp.get_json()["project"]["id"]

    # Export portable .haluro archive
    exp_resp = test_client.get(f"/api/projects/{orig_pid}/export")
    assert exp_resp.status_code == 200
    archive_bytes = exp_resp.data
    assert len(archive_bytes) > 100

    # Delete original project and wipe uploads
    assert test_client.delete(f"/api/projects/{orig_pid}").status_code == 200
    (uploads / f1).unlink()

    # Import archive back
    imp_resp = test_client.post(
        "/api/projects/import",
        data={"file": (io.BytesIO(archive_bytes), "Archivo_Portable.haluro")},
        content_type="multipart/form-data",
    )
    assert imp_resp.status_code == 200, imp_resp.get_data(as_text=True)
    new_proj = imp_resp.get_json()["project"]
    assert new_proj["id"] != orig_pid
    assert new_proj["name"] == "Archivo Portable"
    assert new_proj["frame_count"] == 1

    # Load imported project and verify recipe + restored file
    load_resp = test_client.get(f"/api/projects/{new_proj['id']}")
    assert load_resp.status_code == 200
    loaded = load_resp.get_json()
    assert loaded["missing_files"] == []
    assert loaded["project"]["frames"][0]["simRecipe"]["film"] == "cinestill800t"
    assert (uploads / f1).is_file()

    # Zip-slip archive must be rejected with 400
    bad_zip = io.BytesIO()
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
    bad_zip.seek(0)
    bad_resp = test_client.post(
        "/api/projects/import",
        data={"file": (bad_zip, "evil.haluro")},
        content_type="multipart/form-data",
    )
    assert bad_resp.status_code == 400
