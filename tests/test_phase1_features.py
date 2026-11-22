"""Tests for Phase 1 features: film strength, pre-emulsion WB, B&W optical filters, and user presets library."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.pipeline import develop_frame


def _color_test_image() -> np.ndarray:
    """Synthetic linear RGB image with distinct red, green, and blue quadrants."""
    img = np.zeros((32, 32, 3), dtype=np.float32)
    img[:16, :16] = [0.6, 0.1, 0.1]   # Red
    img[:16, 16:] = [0.1, 0.6, 0.1]   # Green
    img[16:, :16] = [0.1, 0.1, 0.6]   # Blue
    img[16:, 16:] = [0.35, 0.35, 0.35]  # Neutral gray
    return img


def test_film_strength_blends_between_neutral_and_full_emulation() -> None:
    """film_strength=0.0 produces neutral sRGB; 0.5 sits strictly between 0.0 and 1.0."""
    lin = _color_test_image()
    base_kw = {"film_key": "velvia50", "grain_mult": 0.0, "halation_mult": 0.0, "vignette_mult": 0.0}
    out_0 = np.asarray(develop_frame(lin, film_strength=0.0, **base_kw), dtype=np.float32)
    out_half = np.asarray(develop_frame(lin, film_strength=0.5, **base_kw), dtype=np.float32)
    out_1 = np.asarray(develop_frame(lin, film_strength=1.0, **base_kw), dtype=np.float32)
    assert not np.allclose(out_0, out_1, atol=3.0)
    expected_mid = 0.5 * out_0 + 0.5 * out_1
    assert np.mean(np.abs(out_half - expected_mid)) < 2.0


def test_sim_temp_and_tint_shift_white_balance_predictably() -> None:
    """Positive sim_temp warms the neutral patch (R > B); negative cools it (B > R)."""
    lin = np.full((16, 16, 3), 0.25, dtype=np.float32)
    warm = np.asarray(
        develop_frame(
            lin, film_key="portra400", film_strength=0.0, sim_temp=0.7,
            grain_mult=0.0, halation_mult=0.0, vignette_mult=0.0,
        ),
        dtype=np.float32,
    )
    cool = np.asarray(
        develop_frame(
            lin, film_key="portra400", film_strength=0.0, sim_temp=-0.7,
            grain_mult=0.0, halation_mult=0.0, vignette_mult=0.0,
        ),
        dtype=np.float32,
    )
    assert warm[..., 0].mean() > warm[..., 2].mean() + 15.0
    assert cool[..., 2].mean() > cool[..., 0].mean() + 15.0


def test_bw_optical_filters_alter_channel_response_on_bw_stocks() -> None:
    """Red #25 filter brightens red quadrant & darkens blue quadrant vs. Blue #47 filter."""
    lin = _color_test_image()
    red_filt = np.asarray(
        develop_frame(
            lin, film_key="hp5", bw_filter="red",
            grain_mult=0.0, halation_mult=0.0, vignette_mult=0.0,
        ),
        dtype=np.float32,
    )
    blue_filt = np.asarray(
        develop_frame(
            lin, film_key="hp5", bw_filter="blue",
            grain_mult=0.0, halation_mult=0.0, vignette_mult=0.0,
        ),
        dtype=np.float32,
    )
    # Red quadrant (top-left) brighter under red filter than under blue filter
    assert red_filt[:16, :16].mean() > blue_filt[:16, :16].mean() + 40.0
    # Blue quadrant (bottom-left) brighter under blue filter than under red filter
    assert blue_filt[16:, :16].mean() > red_filt[16:, :16].mean() + 40.0


def test_presets_api_crud_and_export_import(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Full CRUD + export/import lifecycle for /api/presets."""
    import app as haluro_app

    monkeypatch.setattr(haluro_app, "USER_DATA_ROOT", tmp_path.resolve())
    haluro_app.app.config["TESTING"] = True

    with haluro_app.app.test_client() as client:
        headers = {"X-Haluro-Token": haluro_app.API_TOKEN}

        # Initially empty
        r0 = client.get("/api/presets")
        assert r0.status_code == 200
        assert r0.get_json()["presets"] == []

        # Save a simulation preset including Phase 1 params
        save_resp = client.post(
            "/api/presets",
            json={
                "name": "HP5 Calle Rojo",
                "notes": "Filtro #25 + grano ASA 800",
                "mode": "simulation",
                "recipe": {
                    "film": "hp5",
                    "film_strength": 0.85,
                    "sim_temp": 0.1,
                    "sim_tint": -0.05,
                    "bw_filter": "red",
                    "grain_asa": "800",
                },
            },
            headers=headers,
        )
        assert save_resp.status_code == 200
        saved = save_resp.get_json()["preset"]
        pid = saved["id"]
        assert saved["name"] == "HP5 Calle Rojo"
        assert saved["recipe"]["bw_filter"] == "red"

        # Export JSON
        exp = client.get("/api/presets/export")
        assert exp.status_code == 200
        exported_json = json.loads(exp.data.decode("utf-8"))
        assert len(exported_json["presets"]) == 1

        # Delete preset
        dele = client.delete(f"/api/presets/{pid}", headers=headers)
        assert dele.status_code == 200
        assert dele.get_json()["presets"] == []

        # Import back via file upload
        imp = client.post(
            "/api/presets/import",
            data={"file": (io.BytesIO(exp.data), "haluro_presets.json")},
            content_type="multipart/form-data",
            headers=headers,
        )
        assert imp.status_code == 200
        imp_data = imp.get_json()
        assert imp_data["added"] == 1
        assert len(imp_data["presets"]) == 1
        assert imp_data["presets"][0]["name"] == "HP5 Calle Rojo"


def test_preview_endpoint_accepts_phase1_parameters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """POST /api/preview accepts film_strength, sim_temp, sim_tint, and bw_filter cleanly."""
    import app as haluro_app

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    haluro_app.app.config["TESTING"] = True

    buf = io.BytesIO()
    Image.new("RGB", (48, 48), (180, 90, 60)).save(buf, format="JPEG")
    buf.seek(0)

    with haluro_app.app.test_client() as client:
        headers = {"X-Haluro-Token": haluro_app.API_TOKEN}
        up = client.post(
            "/api/upload",
            data={"file": (buf, "phase1.jpg")},
            content_type="multipart/form-data",
            headers=headers,
        )
        assert up.status_code == 200
        fname = up.get_json()["filename"]

        prev = client.post(
            "/api/preview",
            json={
                "filename": fname,
                "film": "hp5",
                "film_strength": 0.75,
                "sim_temp": 0.25,
                "sim_tint": -0.1,
                "bw_filter": "orange",
                "include_original": False,
            },
            headers=headers,
        )
        assert prev.status_code == 200, prev.get_data(as_text=True)
        assert prev.get_json()["developed"].startswith("data:image/jpeg;base64,")
