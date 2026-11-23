"""Tests for Phase 1 Optical Upscaling, IBP Super-Resolution, Print cm/DPI calculator, and 1:1 Loupe."""

import numpy as np
from PIL import Image

from app import API_TOKEN, app
from engine.pipeline import develop_frame, save_output_image
from engine.superres import (
    apply_clarity_and_texture,
    apply_optical_dehaze,
    apply_output_sharpen_media,
    apply_richardson_lucy_deconv,
    compute_target_dimensions,
    upscale_float_rgb,
)


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


def test_phase2_deconv_clarity_dehaze_and_output_sharpen():
    import scipy.ndimage

    # Build a slightly blurred edge for deconvolution recovery
    sharp = np.zeros((48, 48, 3), dtype=np.float32)
    sharp[12:36, 12:36, :] = 0.78
    sharp[18:30, 18:30, :] = 0.22
    blurred = np.stack([scipy.ndimage.gaussian_filter(sharp[..., c], sigma=1.2) for c in range(3)], axis=-1)

    deconv = apply_richardson_lucy_deconv(blurred, radius=1.2, amount=0.8)
    assert float(np.abs(np.diff(deconv[..., 0], axis=1)).max()) > float(
        np.abs(np.diff(blurred[..., 0], axis=1)).max()
    )

    # Clarity & Texture increase local contrast without blowing out [0..1]
    cl_out = apply_clarity_and_texture(blurred, clarity=0.6, texture=0.5, protect_skin=True)
    assert cl_out.shape == blurred.shape and float(cl_out.min()) >= 0.0 and float(cl_out.max()) <= 1.0
    assert cl_out.std() > blurred.std()

    # Dehaze increases contrast on a hazy veiled linear image
    hazy = 0.35 + 0.45 * sharp
    dehazed = apply_optical_dehaze(hazy, amount=0.7)
    assert float(dehazed.std()) > float(hazy.std())

    # Output sharpen media (matte > screen > off) with halo suppression
    s_matte = apply_output_sharpen_media(blurred, media="matte", amount=1.0, halo_suppress=0.8)
    assert float(np.abs(np.diff(s_matte[..., 0], axis=1)).max()) > float(
        np.abs(np.diff(blurred[..., 0], axis=1)).max()
    )

    # Full pipeline integration check
    img = Image.fromarray((blurred * 255).astype(np.uint8), mode="RGB")
    dev = develop_frame(
        img,
        film_key="trix400",
        deconv_amount=0.5,
        deconv_radius=1.1,
        clarity=0.4,
        texture=0.3,
        dehaze=0.3,
        output_sharpen_media="glossy",
    )
    assert dev.size == img.size
