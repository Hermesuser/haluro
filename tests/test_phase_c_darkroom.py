"""Tests for Phase C features: multi-mode test strips (exposure, contrast, toner) and digital contact negative."""

import numpy as np
from PIL import Image

from app import app
from engine.pipeline import apply_digital_negative_contact, save_output_image


def test_digital_negative_contact_inverts_and_flips():
    # Left half black (0), right half white (255)
    arr = np.zeros((32, 64, 3), dtype=np.uint8)
    arr[:, 32:, :] = 255
    img = Image.fromarray(arr, mode="RGB")

    neg_img, neg_f = apply_digital_negative_contact(img)
    assert neg_img.size == img.size
    assert neg_f.shape == (32, 64, 3)

    # Original right half (white) becomes black AND flipped to left half!
    # Original left half (black) becomes white AND flipped to right half!
    assert float(neg_f[:, :30, :].mean()) < 0.05
    assert float(neg_f[:, 34:, :].mean()) > 0.95
    # Pure monochrome (R == G == B)
    assert np.allclose(neg_f[..., 0], neg_f[..., 1])
    assert np.allclose(neg_f[..., 1], neg_f[..., 2])


def test_save_output_image_digital_negative(tmp_path):
    arr = np.full((24, 24, 3), 240, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    out_path = tmp_path / "contact_neg.png"
    save_output_image(img, out_path, digital_negative=True)
    assert out_path.is_file()
    loaded = np.asarray(Image.open(out_path).convert("RGB"), dtype=np.float32) / 255.0
    # Bright positive (240/255) inverted to dark negative
    assert float(loaded.mean()) < 0.2


def test_api_test_strip_contrast_and_toner_modes():
    client = app.test_client()
    token_res = client.get("/api/films")
    assert token_res.status_code == 200
    from app import API_TOKEN

    headers = {"X-Haluro-Token": API_TOKEN}

    for strip_mode, expected_first_label in (
        ("exposure", "-1.0 EV"),
        ("contrast", "N−2"),
        ("toner", "0%"),
    ):
        res = client.post(
            "/api/test_strip",
            json={
                "mode": "simulation",
                "filename": "SAMPLE.CR2",
                "film": "trix400",
                "strip_mode": strip_mode,
                "step_ev": 0.5,
            },
            headers=headers,
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["strip_mode"] == strip_mode
        assert len(body["steps"]) == 5
        assert body["steps"][0]["label"] == expected_first_label
        assert body["strip"].startswith("data:image/jpeg;base64,")
