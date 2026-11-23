"""Haluro Optical Upscaling, Iterative Back-Projection (IBP) Super-Resolution & Detail Engine.

100% local, zero heavy ML dependencies (pure NumPy + SciPy + Pillow), float32 16-bit safe,
with automatic tiled execution to keep memory bounded on large 4x enlargements.
"""

from __future__ import annotations

import math

import numpy as np
import scipy.ndimage
from PIL import Image

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

MAX_UPSCALE_LONG_EDGE = 16384
VALID_UPSCALE_MODES = ("off", "lanczos", "ibp")
VALID_UPSCALE_FACTORS = (1.0, 1.5, 2.0, 3.0, 4.0)


def compute_target_dimensions(
    src_w: int,
    src_h: int,
    upscale_factor: float = 1.0,
    print_width_cm: float = 0.0,
    print_height_cm: float = 0.0,
    print_dpi: int = 300,
    max_long_edge: int = MAX_UPSCALE_LONG_EDGE,
) -> tuple[int, int, float]:
    """Compute safe output (width, height, effective_factor) from factor or physical print cm @ DPI."""
    sw = max(1, int(src_w))
    sh = max(1, int(src_h))
    dpi = max(72, min(1200, int(print_dpi or 300)))

    factor = max(1.0, min(4.0, float(upscale_factor or 1.0)))

    # Physical print size overrides factor when specified (> 0)
    pw = float(print_width_cm or 0.0)
    ph = float(print_height_cm or 0.0)
    if pw > 0.5 or ph > 0.5:
        target_w_px = (pw / 2.54) * dpi if pw > 0.5 else 0.0
        target_h_px = (ph / 2.54) * dpi if ph > 0.5 else 0.0
        # Fit preserving source orientation / aspect ratio
        if sw >= sh:
            long_target = max(target_w_px, target_h_px)
            factor = max(1.0, long_target / float(sw))
        else:
            long_target = max(target_w_px, target_h_px)
            factor = max(1.0, long_target / float(sh))
        factor = min(4.0, factor)

    out_w = max(1, int(round(sw * factor)))
    out_h = max(1, int(round(sh * factor)))

    # Enforce RAM safety ceiling on long edge
    long_edge = max(out_w, out_h)
    if max_long_edge > 0 and long_edge > max_long_edge:
        clamp_scale = float(max_long_edge) / float(long_edge)
        out_w = max(1, int(round(out_w * clamp_scale)))
        out_h = max(1, int(round(out_h * clamp_scale)))

    eff_factor = max(out_w / float(sw), out_h / float(sh))
    return out_w, out_h, round(eff_factor, 4)


def _resize_float_lanczos(arr: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """High-precision float32 Lanczos-3 resize per channel using Pillow."""
    if arr.shape[1] == out_w and arr.shape[0] == out_h:
        return arr.astype(np.float32, copy=True)
    chans = []
    for c in range(arr.shape[2]):
        pil_c = Image.fromarray(np.ascontiguousarray(arr[..., c], dtype=np.float32), mode="F")
        resized = pil_c.resize((out_w, out_h), Image.Resampling.LANCZOS)
        chans.append(np.asarray(resized, dtype=np.float32))
    return np.clip(np.stack(chans, axis=-1), 0.0, 1.0)


def _ibp_upscale_tile(
    tile_f: np.ndarray,
    out_w: int,
    out_h: int,
    iterations: int = 4,
    detail_boost: float = 0.28,
) -> np.ndarray:
    """Iterative Back-Projection (IBP) + edge-directed luminance detail reconstruction on a float32 tile."""
    src_h, src_w = tile_f.shape[:2]
    est = _resize_float_lanczos(tile_f, out_w, out_h)

    scale = max(out_w / float(max(1, src_w)), out_h / float(max(1, src_h)))
    psf_sigma = max(0.45, min(1.25, 0.42 * scale))
    step_gain = 0.65

    for _ in range(max(1, int(iterations))):
        # Simulate forward imaging PSF and downsample back to source grid
        blurred = np.stack(
            [scipy.ndimage.gaussian_filter(est[..., c], sigma=psf_sigma) for c in range(3)],
            axis=-1,
        )
        down = _resize_float_lanczos(blurred, src_w, src_h)
        residual = tile_f - down
        # Back-project residual to high-resolution grid with smooth edge-preserving damping
        err_up = _resize_float_lanczos(residual, out_w, out_h)
        est = np.clip(est + step_gain * err_up, 0.0, 1.0)

    # Subtle luminance-only edge-protected micro-acutance to restore crisp diagonal edges without color halos
    boost = float(np.clip(detail_boost, 0.0, 0.8))
    if boost > 0.01:
        y = np.sum(est * LUMA, axis=-1)
        y_blur = scipy.ndimage.gaussian_filter(y, sigma=0.85)
        detail = y - y_blur
        # Coring gate suppresses flat-area noise; halo guard caps positive overshoot
        edge_gate = np.clip((np.abs(detail) - 0.010) / 0.025, 0.0, 1.0)
        tonal_guard = 0.35 + 0.65 * (4.0 * y * np.maximum(0.0, 1.0 - y))
        delta = np.clip(detail * edge_gate * tonal_guard * (boost * 1.15), -0.09, 0.065)
        y_new = np.clip(y + delta, 0.0, 1.0)
        ratio = (y_new + 1e-4) / (y + 1e-4)
        est = np.clip(est * ratio[..., None], 0.0, 1.0)

    return est.astype(np.float32)


def _upscale_progressive_block(
    arr_f: np.ndarray,
    out_w: int,
    out_h: int,
    mode: str = "ibp",
    detail_boost: float = 0.28,
) -> np.ndarray:
    """Progressive multi-step upscaling (max 2x per step) for clean edge preservation."""
    cur = np.clip(np.asarray(arr_f, dtype=np.float32), 0.0, 1.0)
    cur_h, cur_w = cur.shape[:2]
    if cur_w == out_w and cur_h == out_h:
        return cur

    if mode == "lanczos":
        return _resize_float_lanczos(cur, out_w, out_h)

    # Step in <=2x hops so 3x/4x enlargements keep crisp edges without ringing
    while cur_w < out_w or cur_h < out_h:
        next_w = min(out_w, int(math.ceil(cur_w * 2.0)))
        next_h = min(out_h, int(math.ceil(cur_h * 2.0)))
        is_final = next_w == out_w and next_h == out_h
        cur = _ibp_upscale_tile(
            cur,
            next_w,
            next_h,
            iterations=4 if is_final else 3,
            detail_boost=detail_boost if is_final else detail_boost * 0.45,
        )
        cur_h, cur_w = cur.shape[:2]
    return cur


def upscale_float_rgb(
    arr_f: np.ndarray,
    target_w: int,
    target_h: int,
    mode: str = "ibp",
    detail_boost: float = 0.28,
) -> np.ndarray:
    """Upscale float32 sRGB [0..1] image to (target_w, target_h) with automatic tiled memory safety."""
    m = str(mode or "ibp").strip().lower()
    if m == "off":
        return np.clip(np.asarray(arr_f, dtype=np.float32), 0.0, 1.0)
    if m not in VALID_UPSCALE_MODES:
        m = "ibp"

    src = np.clip(np.asarray(arr_f, dtype=np.float32), 0.0, 1.0)
    src_h, src_w = src.shape[:2]
    out_w = max(1, int(target_w))
    out_h = max(1, int(target_h))
    if out_w <= src_w and out_h <= src_h:
        return src

    if m == "lanczos" or (out_w * out_h <= 4096 * 4096):
        return _upscale_progressive_block(src, out_w, out_h, mode=m, detail_boost=detail_boost)

    # Tiled IBP execution with 24px source overlap to keep peak RAM bounded on large 4x prints
    scale_x = out_w / float(src_w)
    scale_y = out_h / float(src_h)
    tile_out = 1536
    pad_src = 20
    out = np.zeros((out_h, out_w, 3), dtype=np.float32)

    for y0_out in range(0, out_h, tile_out):
        y1_out = min(out_h, y0_out + tile_out)
        for x0_out in range(0, out_w, tile_out):
            x1_out = min(out_w, x0_out + tile_out)

            # Map destination tile back to source coordinates with padding
            sx0 = max(0, int(math.floor(x0_out / scale_x)) - pad_src)
            sy0 = max(0, int(math.floor(y0_out / scale_y)) - pad_src)
            sx1 = min(src_w, int(math.ceil(x1_out / scale_x)) + pad_src)
            sy1 = min(src_h, int(math.ceil(y1_out / scale_y)) + pad_src)

            sub = src[sy0:sy1, sx0:sx1, :]
            sub_out_w = max(1, int(round((sx1 - sx0) * scale_x)))
            sub_out_h = max(1, int(round((sy1 - sy0) * scale_y)))
            up_sub = _upscale_progressive_block(sub, sub_out_w, sub_out_h, mode=m, detail_boost=detail_boost)

            # Crop interior region matching [y0_out:y1_out, x0_out:x1_out]
            ox0 = max(0, int(round(x0_out - sx0 * scale_x)))
            oy0 = max(0, int(round(y0_out - sy0 * scale_y)))
            need_w = x1_out - x0_out
            need_h = y1_out - y0_out
            crop = up_sub[oy0 : oy0 + need_h, ox0 : ox0 + need_w, :]
            ch, cw = crop.shape[:2]
            out[y0_out : y0_out + ch, x0_out : x0_out + cw, :] = crop

    return np.clip(out, 0.0, 1.0)
