"""Tests for Ansel Adams Zone System development (N-2 .. N+2) in pipeline and API."""

import numpy as np
from PIL import Image

from app import _parse_sim_look_params
from engine.pipeline import VALID_ZONE_DEVS, apply_zone_system_dev, develop_frame


def test_zone_system_dev_normal_is_identity():
    lin = np.linspace(0.0, 1.0, 64, dtype=np.float32).reshape(8, 8, 1)
    rgb = np.repeat(lin, 3, axis=-1)
    out = apply_zone_system_dev(rgb, "N")
    assert np.allclose(out, rgb)


def test_zone_system_dev_anchors_zone_iii_while_moving_highlights():
    # Build a synthetic linear ramp with Zone III (0.045) and Zone VII/VIII (0.50) patches
    patch = np.zeros((2, 2, 3), dtype=np.float32)
    patch[0, 0] = 0.045  # Zone III anchor
    patch[0, 1] = 0.50   # High tone
    patch[1, 0] = 0.010  # Deep shadow (Zone I)
    patch[1, 1] = 0.85   # Highlight (Zone VIII+)

    n_minus_2 = apply_zone_system_dev(patch, "N-2")
    n_plus_2 = apply_zone_system_dev(patch, "N+2")

    # Zone III and deep shadow remain virtually anchored (< 2% relative drift)
    assert np.allclose(n_minus_2[0, 0], 0.045, rtol=0.02)
    assert np.allclose(n_plus_2[0, 0], 0.045, rtol=0.02)
    assert np.allclose(n_minus_2[1, 0], 0.010, rtol=0.02)
    assert np.allclose(n_plus_2[1, 0], 0.010, rtol=0.02)

    # Contraction (N-2) lowers highlight luminance; expansion (N+2) raises it
    assert n_minus_2[0, 1, 0] < 0.50 < n_plus_2[0, 1, 0]
    assert n_minus_2[1, 1, 0] < 0.85 < n_plus_2[1, 1, 0]


def test_develop_frame_accepts_all_zone_devs():
    grad = np.linspace(20, 220, 64, dtype=np.uint8)
    arr = np.broadcast_to(grad[None, :, None], (64, 64, 3)).copy()
    img = Image.fromarray(arr, mode="RGB")

    means = {}
    for zd in VALID_ZONE_DEVS:
        out = develop_frame(img, film_key="trix400", grain_mult=0.0, vignette_mult=0.0, zone_dev=zd)
        means[zd] = float(np.asarray(out, dtype=np.float32).mean())

    assert means["N-2"] < means["N-1"] < means["N"] < means["N+1"] < means["N+2"]


def test_parse_sim_look_params_zone_dev():
    assert _parse_sim_look_params({"zone_dev": "N+2"})["zone_dev"] == "N+2"
    assert _parse_sim_look_params({"zone_dev": "n-1"})["zone_dev"] == "N-1"
    assert _parse_sim_look_params({"zone_dev": "INVALID"})["zone_dev"] == "N"
    assert _parse_sim_look_params({})["zone_dev"] == "N"
