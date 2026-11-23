"""Haluro Optical Upscaling, Iterative Back-Projection (IBP) Super-Resolution & Detail Engine.

100% local, zero heavy ML dependencies (pure NumPy + SciPy + Pillow), float32 16-bit safe,
with automatic tiled execution to keep memory bounded on large 4x enlargements.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import scipy.ndimage
from PIL import Image

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

MAX_UPSCALE_LONG_EDGE = 16384
VALID_UPSCALE_MODES = ("off", "lanczos", "ibp", "ai_local")
VALID_UPSCALE_FACTORS = (1.0, 1.5, 2.0, 3.0, 4.0)
VALID_OUTPUT_SHARPEN_MEDIA = ("off", "screen", "glossy", "matte")


def find_local_ai_upscaler() -> Path | None:
    """Locate an optional user-installed realesrgan-ncnn-vulkan binary without bundling heavy ML runtimes."""
    env_bin = os.environ.get("HALURO_REALESRGAN_BIN", "").strip()
    if env_bin:
        p = Path(env_bin).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    found = shutil.which("realesrgan-ncnn-vulkan")
    if found:
        return Path(found)
    return None


def _upscale_with_local_ai(arr_f: np.ndarray, out_w: int, out_h: int) -> np.ndarray | None:
    """Run optional local realesrgan-ncnn-vulkan binary via temp PNG; returns None on fallback."""
    binary = find_local_ai_upscaler()
    if not binary:
        return None
    src_h, src_w = arr_f.shape[:2]
    req_scale = max(out_w / float(max(1, src_w)), out_h / float(max(1, src_h)))
    ai_scale = 2 if req_scale <= 2.1 else (3 if req_scale <= 3.1 else 4)
    try:
        with tempfile.TemporaryDirectory(prefix="haluro_ai_") as tmpdir:
            in_path = Path(tmpdir) / "in.png"
            out_path = Path(tmpdir) / "out.png"
            src_u8 = (np.clip(arr_f, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
            Image.fromarray(src_u8, mode="RGB").save(in_path, format="PNG")
            proc = subprocess.run(
                [str(binary), "-i", str(in_path), "-o", str(out_path), "-s", str(ai_scale)],
                capture_output=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0 or not out_path.is_file():
                return None
            out_im = Image.open(out_path).convert("RGB")
            if out_im.size != (out_w, out_h):
                out_im = out_im.resize((out_w, out_h), Image.Resampling.LANCZOS)
            return np.clip(np.asarray(out_im, dtype=np.float32) / 255.0, 0.0, 1.0)
    except Exception:
        return None


def apply_dejpeg_antimoire(lin_f: np.ndarray, strength: float = 0.0) -> np.ndarray:
    """Suppress JPEG 8x8 block artifacts, chroma bleed, and scanner color moire before upscaling."""
    amt = float(np.clip(strength or 0.0, 0.0, 1.0))
    if amt < 0.01:
        return lin_f

    arr = np.maximum(np.asarray(lin_f, dtype=np.float32), 0.0)
    y = np.sum(arr * LUMA, axis=-1, keepdims=True)
    # 1. Chroma moire & JPEG 4:2:0 chroma block suppression (opponent color channels)
    chroma = arr - y
    c_sigma = 0.9 + 1.4 * amt
    chroma_clean = np.stack(
        [scipy.ndimage.gaussian_filter(chroma[..., c], sigma=c_sigma) for c in range(3)],
        axis=-1,
    )
    chroma_out = chroma * (1.0 - 0.80 * amt) + chroma_clean * (0.80 * amt)

    # 2. Edge-preserving flat-zone luminance deblocking
    y2d = y[..., 0]
    y_smooth = scipy.ndimage.gaussian_filter(y2d, sigma=0.75 + 0.65 * amt)
    grad = np.abs(y2d - y_smooth)
    flat_mask = np.clip(1.0 - grad / max(0.015, 0.045 * amt + 0.015), 0.0, 1.0)
    y_out = y2d * (1.0 - 0.55 * amt * flat_mask) + y_smooth * (0.55 * amt * flat_mask)

    return np.maximum(0.0, y_out[..., None] + chroma_out).astype(np.float32)


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

    if m == "ai_local":
        ai_res = _upscale_with_local_ai(src, out_w, out_h)
        if ai_res is not None:
            return ai_res
        m = "ibp"

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


def apply_richardson_lucy_deconv(
    arr_f: np.ndarray,
    radius: float = 1.0,
    amount: float = 0.0,
    coring: float = 0.012,
) -> np.ndarray:
    """Damped luminance-only Richardson-Lucy optical deconvolution (lens/scanner PSF recovery)."""
    amt = float(np.clip(amount or 0.0, 0.0, 1.0))
    if amt < 0.01:
        return arr_f

    arr = np.clip(np.asarray(arr_f, dtype=np.float32), 0.0, 1.0)
    sigma = float(np.clip(radius or 1.0, 0.5, 2.5))
    iters = max(2, int(round(3 + 7 * amt)))

    y = np.sum(arr * LUMA, axis=-1)
    est = np.maximum(y, 1e-4).copy()

    for _ in range(iters):
        conv = scipy.ndimage.gaussian_filter(est, sigma=sigma)
        rel_blur = y / np.maximum(conv, 1e-4)
        # Clamp extreme noise spikes before back-convolution
        rel_blur = np.clip(rel_blur, 0.4, 2.2)
        corr = scipy.ndimage.gaussian_filter(rel_blur, sigma=sigma)
        est = np.clip(est * corr, 0.0, 1.0)

    delta = est - y
    # Noise coring gate protects smooth skies and deep shadow grain
    thr = max(0.004, float(coring))
    edge_gate = np.clip((np.abs(delta) - thr) / (thr * 2.5), 0.0, 1.0)
    # Asymmetric halo guard: suppress harsh white overshoot more strictly than dark edge crispness
    delta_clamped = np.clip(delta * edge_gate * amt, -0.18, 0.11)
    y_out = np.clip(y + delta_clamped, 0.0, 1.0)

    ratio = (y_out + 1e-4) / (y + 1e-4)
    return np.clip(arr * ratio[..., None], 0.0, 1.0).astype(np.float32)


def apply_optical_dehaze(lin_f: np.ndarray, amount: float = 0.0) -> np.ndarray:
    """Dark-Channel Prior atmospheric dehaze / vintage lens veiling-flare removal in linear light."""
    amt = float(np.clip(amount or 0.0, -0.5, 1.0))
    if abs(amt) < 0.01:
        return lin_f

    x = np.maximum(np.asarray(lin_f, dtype=np.float32), 0.0)
    if amt < 0.0:
        # Negative dehaze adds subtle soft atmospheric mist/glow
        mist = abs(amt) * 0.22
        y = np.sum(x * LUMA, axis=-1, keepdims=True)
        glow = scipy.ndimage.gaussian_filter(y[..., 0], sigma=max(6.0, min(x.shape[:2]) * 0.02))[..., None]
        return np.maximum(0.0, x * (1.0 - 0.15 * mist) + (0.04 + 0.35 * glow) * mist)

    # Dark channel (minimum across RGB channels in local neighborhood)
    patch = max(5, min(21, int(min(x.shape[:2]) * 0.025) | 1))
    min_rgb = np.min(x, axis=-1)
    dark_raw = scipy.ndimage.minimum_filter(min_rgb, size=patch)
    dark_smooth = scipy.ndimage.gaussian_filter(dark_raw, sigma=max(4.0, patch * 0.6))

    # Estimate atmospheric veil color from top 0.5% brightest dark-channel pixels (capped safely)
    flat_dark = dark_raw.ravel()
    k = max(1, int(flat_dark.size * 0.005))
    top_idx = np.argpartition(flat_dark, -k)[-k:]
    flat_x = x.reshape(-1, 3)
    airlight = np.clip(np.mean(flat_x[top_idx], axis=0), 0.35, 1.4).astype(np.float32)
    air_min = float(np.min(airlight))

    transmission = np.clip(1.0 - (0.78 * amt) * (dark_smooth / max(air_min, 0.25)), 0.28, 1.0)
    recovered = (x - airlight[None, None, :]) / transmission[..., None] + airlight[None, None, :]
    return np.maximum(0.0, recovered).astype(np.float32)


def apply_clarity_and_texture(
    arr_f: np.ndarray,
    clarity: float = 0.0,
    texture: float = 0.0,
    protect_skin: bool = False,
) -> np.ndarray:
    """Multi-scale luminance local microcontrast (Clarity) and fine detail (Texture) without halos."""
    cl = float(np.clip(clarity or 0.0, -1.0, 1.0))
    tx = float(np.clip(texture or 0.0, -1.0, 1.0))
    if abs(cl) < 0.01 and abs(tx) < 0.01:
        return arr_f

    arr = np.clip(np.asarray(arr_f, dtype=np.float32), 0.0, 1.0)
    y = np.sum(arr * LUMA, axis=-1)
    delta_y = np.zeros_like(y)

    # Optional skin-tone & smooth-sky protection mask
    prot_mask = 1.0
    if protect_skin and (cl > 0.0 or tx > 0.0):
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        skin = (
            np.clip((r - g) / 0.14, 0.0, 1.0)
            * np.clip((g - b) / 0.10, 0.0, 1.0)
            * np.clip((r - 0.18) / 0.25, 0.0, 1.0)
            * np.clip((0.92 - b) / 0.25, 0.0, 1.0)
        )
        skin_smooth = scipy.ndimage.gaussian_filter(skin, sigma=2.5)
        prot_mask = 1.0 - 0.65 * np.clip(skin_smooth, 0.0, 1.0)

    if abs(cl) >= 0.01:
        sigma_mid = max(6.0, min(28.0, min(arr.shape[:2]) * 0.018))
        y_mid = scipy.ndimage.gaussian_filter(y, sigma=sigma_mid)
        mid_detail = y - y_mid
        mid_bell = 4.0 * y * np.maximum(0.0, 1.0 - y)
        cl_eff = cl * (prot_mask if cl > 0.0 else 1.0)
        delta_y += np.clip(mid_detail * (0.48 * cl_eff) * (0.25 + 0.75 * mid_bell), -0.16, 0.14)

    if abs(tx) >= 0.01:
        y_fine = scipy.ndimage.gaussian_filter(y, sigma=1.2)
        y_med = scipy.ndimage.gaussian_filter(y, sigma=3.6)
        tex_band = y_fine - y_med
        tx_eff = tx * (prot_mask if tx > 0.0 else 1.0)
        delta_y += np.clip(tex_band * (0.75 * tx_eff), -0.12, 0.10)

    y_out = np.clip(y + delta_y, 0.0, 1.0)
    ratio = (y_out + 1e-4) / (y + 1e-4)
    return np.clip(arr * ratio[..., None], 0.0, 1.0).astype(np.float32)


def apply_output_sharpen_media(
    arr_f: np.ndarray,
    media: str = "off",
    amount: float = 1.0,
    halo_suppress: float = 0.5,
) -> np.ndarray:
    """Output sharpening calibrated for Screen Web, Glossy/Baryta Paper, or Matte Cotton Paper."""
    key = str(media or "off").strip().lower()
    amt = float(np.clip(amount or 0.0, 0.0, 2.0))
    if key == "off" or key not in VALID_OUTPUT_SHARPEN_MEDIA or amt < 0.01:
        return arr_f

    # Calibrated radii & gains per physical output surface
    specs = {
        "screen": (0.65, 0.55),  # crisp sub-pixel web viewing
        "glossy": (0.95, 0.78),  # fiber baryta / RC glossy print
        "matte": (1.35, 1.05),   # cotton rag matte dot-gain compensation
    }
    sigma, base_gain = specs[key]
    arr = np.clip(np.asarray(arr_f, dtype=np.float32), 0.0, 1.0)
    y = np.sum(arr * LUMA, axis=-1)
    detail = y - scipy.ndimage.gaussian_filter(y, sigma=sigma)

    edge_gate = np.clip((np.abs(detail) - 0.008) / 0.020, 0.0, 1.0)
    tonal_guard = 0.30 + 0.70 * (4.0 * y * np.maximum(0.0, 1.0 - y))
    raw_delta = detail * edge_gate * tonal_guard * (base_gain * amt)

    # Asymmetric halo suppression caps positive white rims strictly when halo_suppress -> 1.0
    hs = float(np.clip(halo_suppress if halo_suppress is not None else 0.5, 0.0, 1.0))
    pos_cap = 0.14 - 0.095 * hs  # 0.14 down to 0.045
    neg_cap = -0.16 + 0.04 * hs
    delta = np.clip(raw_delta, neg_cap, pos_cap)

    y_out = np.clip(y + delta, 0.0, 1.0)
    ratio = (y_out + 1e-4) / (y + 1e-4)
    return np.clip(arr * ratio[..., None], 0.0, 1.0).astype(np.float32)
