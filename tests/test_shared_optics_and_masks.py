"""Tests for shared optical cleanup, denoise, defringe, dust healing, and Dodge & Burn masks."""

import numpy as np
from PIL import Image

from app import app as flask_app
from engine.negative_inverter import apply_dust_spot_healing as neg_heal
from engine.pipeline import (
    apply_defringe,
    apply_digital_denoise,
    apply_dust_spot_healing,
    apply_local_dodge_burn,
    develop_frame,
)


def test_shared_dust_heal_reexport_and_effect():
    assert neg_heal is apply_dust_spot_healing
    img = np.full((64, 64, 3), 0.4, dtype=np.float32)
    img[30:34, 30:34] = 1.0  # bright dust speck
    healed = apply_dust_spot_healing(img, [{"x": 0.5, "y": 0.5, "r": 0.06}])
    assert healed.shape == img.shape
    assert float(healed[32, 32].mean()) < 0.6


def test_digital_denoise_smooths_chroma_and_luma_noise():
    rng = np.random.default_rng(7)
    clean = np.full((64, 64, 3), 0.35, dtype=np.float32)
    noisy = np.clip(clean + rng.normal(0.0, 0.08, size=clean.shape).astype(np.float32), 0.0, 1.0)
    denoised = apply_digital_denoise(noisy, luma_strength=0.8, chroma_strength=0.9)
    assert denoised.shape == noisy.shape
    assert np.std(denoised) < np.std(noisy)


def test_defringe_reduces_purple_fringe():
    img = np.zeros((48, 48, 3), dtype=np.float32)
    img[:, :24] = 0.05
    img[:, 24:] = 0.9
    # Inject artificial magenta fringe on the edge
    img[:, 23:25, 0] = 0.95
    img[:, 23:25, 1] = 0.15
    img[:, 23:25, 2] = 0.95
    out = apply_defringe(img, strength=1.0)
    fringe_before = float(np.mean(np.minimum(img[:, 23:25, 0], img[:, 23:25, 2]) - img[:, 23:25, 1]))
    fringe_after = float(np.mean(np.minimum(out[:, 23:25, 0], out[:, 23:25, 2]) - out[:, 23:25, 1]))
    assert fringe_after < fringe_before


def test_local_dodge_burn_linear_and_radial():
    base = np.full((64, 64, 3), 0.25, dtype=np.float32)
    grad_out = apply_local_dodge_burn(
        base,
        [{"type": "linear", "x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0, "ev": -1.0, "feather": 0.5}],
    )
    assert float(grad_out[2, 32].mean()) < float(grad_out[60, 32].mean())

    radial_out = apply_local_dodge_burn(
        base,
        [{"type": "radial", "x1": 0.5, "y1": 0.5, "x2": 0.75, "y2": 0.75, "ev": 1.0, "feather": 0.5}],
    )
    assert float(radial_out[32, 32].mean()) > float(radial_out[2, 2].mean())


def test_develop_frame_with_shared_optics_and_masks():
    pil_in = Image.fromarray(np.full((64, 64, 3), 120, dtype=np.uint8))
    out = develop_frame(
        pil_in,
        film_key="portra400",
        denoise_luma=0.3,
        denoise_chroma=0.4,
        defringe=0.5,
        dust_spots=[{"x": 0.5, "y": 0.5, "r": 0.02}],
        local_masks=[{"type": "radial", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.8, "ev": 0.5, "feather": 0.5}],
        sharpen_mode="lab",
        sharpen_amount=1.0,
    )
    assert out.size == (64, 64)


def test_preview_endpoint_accepts_shared_optics(tmp_path):
    from app import API_TOKEN, UPLOAD_DIR

    fname = "test_optics_frame.png"
    fpath = UPLOAD_DIR / fname
    Image.fromarray(np.full((48, 48, 3), 110, dtype=np.uint8)).save(fpath)
    try:
        client = flask_app.test_client()
        resp = client.post(
            "/api/preview",
            headers={"X-Haluro-Token": API_TOKEN},
            json={
                "filename": fname,
                "film": "portra400",
                "denoise_luma": 0.25,
                "denoise_chroma": 0.4,
                "defringe": 0.3,
                "sharpen_mode": "lab",
                "sharpen_amount": 1.1,
                "dust_spots": [{"x": 0.4, "y": 0.4, "r": 0.01}],
                "local_masks": [{"type": "linear", "x1": 0.5, "y1": 0.1, "x2": 0.5, "y2": 0.6, "ev": -0.5}],
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["developed"].startswith("data:image/jpeg;base64,")
    finally:
        if fpath.exists():
            fpath.unlink()


def test_linear_mask_feather_controls_transition_band():
    from engine.pipeline import apply_local_dodge_burn

    lin = np.full((100, 32, 3), 0.4, dtype=np.float32)
    hard = apply_local_dodge_burn(
        lin,
        [{"type": "linear", "x1": 0.5, "y1": 0.1, "x2": 0.5, "y2": 0.9, "ev": 1.0, "feather": 0.1}],
    )
    soft = apply_local_dodge_burn(
        lin,
        [{"type": "linear", "x1": 0.5, "y1": 0.1, "x2": 0.5, "y2": 0.9, "ev": 1.0, "feather": 1.0}],
    )
    # At y=25% (between y1=10% and midpoint=50%), hard feather stays fully at +1 EV while soft is already tapering
    assert float(hard[25, 16, 0]) > float(soft[25, 16, 0]) + 0.05
