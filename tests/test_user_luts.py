"""Tests for user-imported `.cube` LUTs support."""

from __future__ import annotations

import io

import numpy as np

from engine.films import delete_user_lut, get_film, get_user_luts_dir, list_films, save_user_lut
from engine.pipeline import develop_frame


def _identity_2x2x2_cube() -> bytes:
    """Return a minimal valid 2x2x2 identity 3D `.cube` file."""
    lines = ["TITLE \"Identity 2x2x2\"", "LUT_3D_SIZE 2"]
    for b in (0.0, 1.0):
        for g in (0.0, 1.0):
            for r in (0.0, 1.0):
                lines.append(f"{r:.6f} {g:.6f} {b:.6f}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_save_list_develop_and_delete_user_lut(monkeypatch, tmp_path):
    monkeypatch.setenv("HALURO_DATA_DIR", str(tmp_path))

    # Double .cube.cube extension is normalized to .cube
    entry = save_user_lut("My Film.cube.cube", _identity_2x2x2_cube(), lut_space="srgb")
    assert entry["key"] == "user:my_film"
    assert entry["kind"] == "user"
    assert entry["is_user_lut"] is True
    assert (get_user_luts_dir() / "My Film.cube").is_file()

    # Included in list_films() and resolvable via get_film()
    all_keys = {f["key"] for f in list_films()}
    assert "user:my_film" in all_keys
    film = get_film("user:my_film")
    assert film["is_user_lut"] is True
    assert film["lut_file"].endswith("My Film.cube")

    # Develop a small synthetic linear image using the user LUT
    lin = np.full((16, 16, 3), 0.25, dtype=np.float32)
    out = develop_frame(lin, film_key="user:my_film", grain_mult=0.0, halation_mult=0.0, vignette_mult=0.0)
    assert out.size == (16, 16)
    arr = np.asarray(out)
    assert arr.shape == (16, 16, 3)
    assert np.isfinite(arr).all()

    # Delete user LUT
    assert delete_user_lut("user:my_film") is True
    assert not (get_user_luts_dir() / "My Film.cube").exists()
    assert delete_user_lut("user:my_film") is False


def test_rejects_invalid_or_corrupt_cube(monkeypatch, tmp_path):
    monkeypatch.setenv("HALURO_DATA_DIR", str(tmp_path))

    import pytest

    with pytest.raises(ValueError, match="extensión .cube"):
        save_user_lut("not_a_lut.txt", _identity_2x2x2_cube())

    corrupt = b"LUT_3D_SIZE 33\n0.1 0.2 0.3\n65 0.9\n"
    with pytest.raises(ValueError):
        save_user_lut("corrupt.cube", corrupt)


def test_user_luts_api_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("HALURO_DATA_DIR", str(tmp_path))

    import app as haluro_app

    client = haluro_app.app.test_client()
    headers = {"X-Haluro-Token": haluro_app.API_TOKEN}

    # Upload valid .cube
    resp = client.post(
        "/api/user_luts",
        data={
            "lut_space": "srgb",
            "files": (io.BytesIO(_identity_2x2x2_cube()), "Warm Look.cube"),
        },
        content_type="multipart/form-data",
        headers=headers,
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True
    assert len(payload["added"]) == 1
    key = payload["added"][0]["key"]
    assert key == "user:warm_look"

    # Listed in /api/films
    films_resp = client.get("/api/films", headers=headers)
    assert films_resp.status_code == 200
    keys = {f["key"] for f in films_resp.get_json()["films"]}
    assert key in keys

    # Delete via API
    del_resp = client.delete(f"/api/user_luts/{key}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.get_json()["success"] is True

    # Deleting again returns 404
    del_again = client.delete(f"/api/user_luts/{key}", headers=headers)
    assert del_again.status_code == 404
