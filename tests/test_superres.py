"""Tests for Phase 1 Optical Upscaling, IBP Super-Resolution, Print cm/DPI calculator, and 1:1 Loupe."""

import numpy as np
from PIL import Image

from app import API_TOKEN, app
from engine.pipeline import develop_frame, save_output_image
from engine.superres import compute_target_dimensions, upscale_float_rgb


def test_compute_target_dimensions_factor_and_print_cm():
    w, h, f = compute_target_dimensions(1000, 500, upscale_factor=2.0)
    assert (w, h) == (2000, 1000) and f == 2.0

    # Physical print 30x20 cm @ 300 DPI => ~3543 px long edge => ~3.54x from 1000px
    pw, ph, pf = compute_target_dimensions(1000, 667, print_width_cm=30.0, print_height_cm=20.0, print_dpi=300)
    assert 3500 <= pw <= 3600
    assert pf > 3.4

    # RAM safety clamp
    cw, ch, _ = compute_target_dimensions(8000, 6000, upscale_factor=4.0, max_long_edge=16384)
    assert max(cw, ch) == 16384


def test_upscale_float_rgb_ibp_and_lanczos_preserve_sharpness():
    # Create a crisp checkerboard edge pattern
    arr = np.zeros((32, 32, 3), dtype=np.float32)
    arr[8:24, 8:24, :] = 0.85
    arr[12:20, 12:20, :] = 0.15

    up_ibp = upscale_float_rgb(arr, 64, 64, mode="ibp")
    up_lan = upscale_float_rgb(arr, 64, 64, mode="lanczos")

    assert up_ibp.shape == (64, 64, 3)
    assert up_lan.shape == (64, 64, 3)
    assert up_ibp.dtype == np.float32
    assert float(up_ibp.min()) >= 0.0 and float(up_ibp.max()) <= 1.0
    # IBP edge gradient should be at least as sharp as Lanczos
    grad_ibp = float(np.abs(np.diff(up_ibp[..., 0], axis=1)).max())
    grad_lan = float(np.abs(np.diff(up_lan[..., 0], axis=1)).max())
    assert grad_ibp >= grad_lan * 0.95


def test_develop_frame_and_save_output_image_upscale(tmp_path):
    arr = np.full((32, 48, 3), 140, dtype=np.uint8)
    arr[10:22, 16:32, :] = 220
    img = Image.fromarray(arr, mode="RGB")

    # Pre-grain upscaling on full-res develop_frame
    dev = develop_frame(img, film_key="trix400", max_dim=None, upscale_factor=2.0, upscale_mode="ibp")
    assert dev.size == (96, 64)

    # save_output_image upscaling path (e.g. negative export)
    out_path = tmp_path / "upscaled_2x.png"
    saved = save_output_image(img, out_path, upscale_factor=2.0, upscale_mode="ibp")
    assert saved.size == (96, 64)
    assert Image.open(out_path).size == (96, 64)


def test_api_inspect_crop_loupe_endpoint():
    client = app.test_client()
    res = client.post(
        "/api/inspect_crop",
        json={
            "mode": "simulation",
            "filename": "SAMPLE.CR2",
            "film": "portra400",
            "cx": 0.5,
            "cy": 0.5,
            "upscale_factor": 2.0,
            "upscale_mode": "ibp",
        },
        headers={"X-Haluro-Token": API_TOKEN},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["before"].startswith("data:image/jpeg;base64,")
    assert body["after"].startswith("data:image/jpeg;base64,")
    assert body["out_w"] >= body["src_w"] * 1.9
    assert body["out_mp"] > 0
