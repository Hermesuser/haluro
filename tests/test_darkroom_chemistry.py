"""Tests for Phase B darkroom chemistry: developers, enlarger heads, B&W print, dual toning, and Farmer bleach."""

import numpy as np
from PIL import Image

from app import _parse_local_masks, _parse_sim_look_params
from engine.pipeline import (
    DEV_PROCESSES,
    VALID_DUAL_HIGHLIGHT_TONERS,
    VALID_DUAL_SHADOW_TONERS,
    VALID_ENLARGER_HEADS,
    VALID_PAPER_BASES,
    VALID_PAPER_DEVELOPERS,
    apply_bw_darkroom_print,
    apply_dual_toning,
    apply_enlarger_head,
    apply_farmer_bleach,
    apply_local_dodge_burn,
    develop_frame,
)


def _sample_gradient_img(size=48):
    grad = np.linspace(15, 240, size, dtype=np.uint8)
    arr = np.broadcast_to(grad[None, :, None], (size, size, 3)).copy()
    return Image.fromarray(arr, mode="RGB")


def test_classic_film_developers_present_and_render():
    img = _sample_gradient_img()
    for key in ("d76_1_1", "d23_divided", "pmk_pyro", "pyrocat_hd", "rodinal_1_50", "windisch_comp"):
        assert key in DEV_PROCESSES
        out = develop_frame(img, film_key="trix400", dev_process=key, vignette_mult=0.0)
        assert out.size == img.size


def test_enlarger_head_condenser_vs_diffuser_contrast():
    img = _sample_gradient_img()
    cond = np.asarray(
        develop_frame(img, film_key="trix400", grain_mult=0.0, vignette_mult=0.0, enlarger_head="condenser"),
        dtype=np.float32,
    )
    diff = np.asarray(
        develop_frame(img, film_key="trix400", grain_mult=0.0, vignette_mult=0.0, enlarger_head="diffuser"),
        dtype=np.float32,
    )
    # Condenser (Callier) yields higher tonal spread (std) than Diffuser (Cold Light)
    assert cond.std() > diff.std()
    assert np.allclose(apply_enlarger_head(cond / 255.0, "standard"), cond / 255.0)


def test_bw_darkroom_print_preflash_and_paper_base():
    ramp = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    rgb = np.repeat(ramp[None, :, None], 3, axis=-1)
    rgb = np.repeat(rgb, 16, axis=0)

    # Pre-flash pulls down Zone VIII-IX highlights without lifting Zone 0-I shadows
    flashed = apply_bw_darkroom_print(rgb, bw_preflash=0.8)
    assert np.allclose(flashed[:, 2, :], rgb[:, 2, :], atol=1e-4)
    assert flashed[:, -2, 0].mean() < rgb[:, -2, 0].mean()

    # Warm ivory paper base warms highlights (R > B)
    ivory = apply_bw_darkroom_print(rgb, paper_base="fb_ivory")
    assert ivory[0, -1, 0] > ivory[0, -1, 2]

    # Matte cotton lifts D-max floor
    matte = apply_bw_darkroom_print(rgb, paper_base="cotton_matte")
    assert matte[0, 0, 0] > 0.02


def test_sequential_dual_toning_shadows_and_highlights():
    ramp = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    rgb = np.repeat(ramp[None, :, None], 3, axis=-1)
    rgb = np.repeat(rgb, 16, axis=0)

    toned = apply_dual_toning(
        rgb,
        toner_shadows="selenium",
        toner_shadows_amt=0.8,
        toner_highlights="sepia",
        toner_highlights_amt=0.8,
    )
    # Shadows get selenium cool-plum cast (B > G in Zone II-III)
    assert toned[0, 12, 2] > toned[0, 12, 1]
    # Highlights get sepia warm cast (R > B in Zone VII-VIII)
    assert toned[0, 48, 0] > toned[0, 48, 2]


def test_farmer_bleach_global_and_local_mask():
    ramp = np.linspace(0.02, 0.75, 64, dtype=np.float32)
    rgb = np.repeat(ramp[None, :, None], 3, axis=-1)
    rgb = np.repeat(rgb, 16, axis=0)

    bleached = apply_farmer_bleach(rgb, amount=0.7)
    # Highlights lift noticeably more than deep shadows
    hi_delta = float(bleached[0, 50, 0] - rgb[0, 50, 0])
    lo_delta = float(bleached[0, 2, 0] - rgb[0, 2, 0])
    assert hi_delta > lo_delta + 0.02

    # Local Farmer mask lifts upper midtones/highlights inside radial region
    lin_out = apply_local_dodge_burn(
        rgb,
        [{"type": "radial", "mode": "farmer", "x1": 0.5, "y1": 0.5, "x2": 1.0, "y2": 1.0, "ev": 1.2, "feather": 0.4}],
    )
    assert float(lin_out[8, 48, 0]) > float(rgb[8, 48, 0])


def test_parse_phase_b_params_and_local_mask_mode():
    parsed = _parse_sim_look_params(
        {
            "enlarger_head": "condenser",
            "paper_dev": "ansco130",
            "paper_base": "fb_ivory",
            "bw_grade00": 0.4,
            "bw_grade5": -0.2,
            "bw_preflash": 0.35,
            "toner_shadows": "selenium",
            "toner_shadows_amt": 0.6,
            "toner_highlights": "sepia",
            "toner_highlights_amt": 0.5,
            "farmer_bleach": 0.25,
        }
    )
    assert parsed["enlarger_head"] in VALID_ENLARGER_HEADS
    assert parsed["paper_dev"] in VALID_PAPER_DEVELOPERS
    assert parsed["paper_base"] in VALID_PAPER_BASES
    assert parsed["toner_shadows"] in VALID_DUAL_SHADOW_TONERS
    assert parsed["toner_highlights"] in VALID_DUAL_HIGHLIGHT_TONERS
    assert parsed["farmer_bleach"] == 0.25

    masks = _parse_local_masks(
        [{"type": "radial", "mode": "farmer", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.8, "ev": 1.0}]
    )
    assert len(masks) == 1 and masks[0]["mode"] == "farmer"
