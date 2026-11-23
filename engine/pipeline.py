"""Complete film development pipeline for RAW & standard images.
Implements exposure, vignette, halation, 3D LUTs, film response curves, and grain.
"""

import functools
import hashlib
import io
import logging
import math
import os
import struct
import unicodedata
import zlib
from pathlib import Path

import numpy as np
import scipy.ndimage
from PIL import Image, ImageCms, ImageDraw, ImageOps

from . import __version__
from .films import LUT_DIR, get_film, resolve_grain_profile
from .lut import load_lut
from .platform_io import is_macos, load_ui_font

try:
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None

logger = logging.getLogger(__name__)

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

REF_COLORS = [
    [1.0, 0.0, 0.0],       # red
    [1.0, 0.5, 0.0],       # orange
    [1.0, 1.0, 0.0],       # yellow
    [0.0, 1.0, 0.0],       # green
    [0.0, 1.0, 1.0],       # cyan
    [0.0, 0.0, 1.0],       # blue
    [1.0, 0.0, 1.0],       # magenta
]

HUE_NAMES = ["red", "orange", "yellow", "green", "cyan", "blue", "magenta"]


def get_hue_angle(idx):
    c = REF_COLORS[idx]
    y = np.dot(c, LUMA)
    cr = (c[0] - y) / 1.5748
    cb = (c[2] - y) / 1.8556
    return math.atan2(cr, cb)


HUE_ANGLES = [get_hue_angle(i) for i in range(7)]


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def srgb_to_linear(srgb):
    """Convert sRGB [0..1] to scene-linear [0..inf].

    Implemented branch by branch instead of with ``np.where``: ``np.where``
    evaluates *both* arms, so a 24 MP frame allocated three extra full-size
    float32 temporaries (648 MB measured, versus 421 MB here) on every
    conversion, and the engine converts 4-8 times per frame.
    """
    srgb = np.maximum(np.asarray(srgb, dtype=np.float32), 0.0)
    out = np.empty_like(srgb, dtype=np.float32)
    low = srgb <= 0.04045
    np.divide(srgb, 12.92, out=out, where=low)
    high = ~low
    if high.any():
        # Work on a partial copy so the offset and the power reuse one buffer
        # instead of allocating three full-size temporaries.
        tmp = srgb[high]
        tmp += 0.055
        tmp /= 1.055
        np.power(tmp, 2.4, out=tmp)
        out[high] = tmp
    return out


def linear_to_srgb(lin, clip=True):
    """Convert scene-linear to sRGB [0..1].

    ``clip=False`` keeps values above 1.0 so intermediate operations (halation,
    glow) are not truncated before they are encoded.
    """
    lin = np.asarray(lin, dtype=np.float32)
    lin = np.clip(lin, 0.0, 1.0) if clip else np.maximum(lin, 0.0)
    out = np.empty_like(lin, dtype=np.float32)
    low = lin <= 0.0031308
    np.multiply(lin, 12.92, out=out, where=low)
    high = ~low
    if high.any():
        tmp = lin[high]
        np.power(tmp, 1 / 2.4, out=tmp)
        tmp *= 1.055
        tmp -= 0.055
        out[high] = tmp
    return out


def apply_characteristic_curve(x, slope, pivot, black, white):
    """Logistic characteristic response curve in log2 exposure around 18% mid grey."""
    x = np.maximum(x, 1e-6)
    xx = np.log2(x / 0.18) - pivot
    k = 4.0 * slope / (white - black)
    return black + (white - black) / (1.0 + np.exp(-k * xx))


def _smoothstep(edge0, edge1, x):
    """Hermite interpolation between two edges, clipped to [0, 1]."""
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def apply_tonal_zones(lin, shadows=0.0, mids=0.0, highlights=0.0):
    """Zonas tonales (sombras / tonos medios / luces) como exposición en luz lineal.

    Un control de zona no es un filtro de color: es un ajuste de exposición
    sobre la luz que llega a la emulsión. Por eso se aplica en luz lineal
    (multiplicar por 2 = un stop), antes de la respuesta de película.

    Las tres máscaras forman una partición de la unidad (suman exactamente 1),
    de modo que las zonas nunca se apilan: subir sombras y medios a la vez
    equivale a un único ajuste ponderado, no a la suma de ambos. Es lo que
    evita el «barro» típico de los controles tonales que se solapan.

    Cada zona tiene meseta (plato) y transiciones suaves: las sombras mandan
    con toda su fuerza en los negros profundos, los medios en el gris medio y
    las luces en las altas luces. Sin meseta, el control de sombras solo
    mordía el punto negro y el de luces el blanco puro.

    Las máscaras se calculan sobre la luminancia *perceptual* (gamma 1/2.2):
    un umbral sobre luz lineal colocaría el gris medio muy abajo y las
    «sombras» se comieron los medios tonos.
    """
    shadows = float(shadows)
    mids = float(mids)
    highlights = float(highlights)
    if abs(shadows) < 1e-4 and abs(mids) < 1e-4 and abs(highlights) < 1e-4:
        return lin

    luma = np.sum(lin * LUMA, axis=-1, keepdims=True)
    # Luminancia perceptual: 0.5 ≈ gris medio (0.218 lineal).
    lp = np.clip(luma, 0.0, 1.0) ** (1.0 / 2.2)

    # Mesetas: sombras (<0.15), medios (0.45-0.55), luces (>0.85).
    w_shadows = 1.0 - _smoothstep(0.15, 0.50, lp)
    w_mids = _smoothstep(0.15, 0.45, lp) * (1.0 - _smoothstep(0.55, 0.85, lp))
    w_highlights = _smoothstep(0.50, 0.85, lp)

    # Normalización: partición exacta de la unidad (las zonas nunca se apilan).
    total = w_shadows + w_mids + w_highlights
    total = np.where(total > 1e-6, total, 1.0)
    w_shadows = w_shadows / total
    w_mids = w_mids / total
    w_highlights = w_highlights / total

    gain_ev = shadows * w_shadows + mids * w_mids + highlights * w_highlights
    return lin * np.power(2.0, gain_ev)


def build_curve_lut(points, size=256):
    """Construye una LUT de 256 entradas a partir de los puntos de control.

    La interpolación es *monótona por tramos* (PCHIP): respeta la forma que el
    fotógrafo ve dibujada y nunca introduce sobreoscilaciones, que en una
    curva tonal producen bandas y dientes en las sombras.

    Los puntos son pares ``[x, y]`` con x en [0, 1] (posición de entrada) e y
    libre (salida). Se permiten salidas fuera de [0, 1] para poder «cortar»
    negros y luces al gusto.
    """
    pts = []
    for p in points or []:
        try:
            x = float(p[0])
            y = float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        pts.append((float(np.clip(x, 0.0, 1.0)), float(np.clip(y, -0.5, 1.5))))
    if not pts:
        return None

    pts.sort(key=lambda t: t[0])
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)

    # Puntos duplicados en x rompen el interpolador: se promedian sus alturas.
    keep_x, keep_y = [], []
    for x, y in zip(xs, ys, strict=True):
        if keep_x and abs(x - keep_x[-1]) < 1e-6:
            keep_y[-1] = 0.5 * (keep_y[-1] + y)
        else:
            keep_x.append(x)
            keep_y.append(y)
    xs = np.array(keep_x, dtype=np.float64)
    ys = np.array(keep_y, dtype=np.float64)

    if len(xs) == 1:
        # Un solo punto define una recta que pasa por (x, y).
        x0, y0 = float(xs[0]), float(ys[0])
        lut = np.clip((np.arange(size, dtype=np.float64) / (size - 1) - x0) + y0, -0.5, 1.5)
        return lut.astype(np.float32)

    grid = np.linspace(0.0, 1.0, size, dtype=np.float64)
    try:
        from scipy.interpolate import PchipInterpolator

        lut = PchipInterpolator(xs, ys, extrapolate=True)(grid)
    except Exception:
        # Respaldo lineal si el interpolador no está disponible.
        lut = np.interp(grid, xs, ys)
    return np.clip(lut, -0.5, 1.5).astype(np.float32)


def apply_user_curves(display, curve_spec):
    """Aplica las curvas de usuario sobre la imagen ya revelada.

    La curva de usuario se evalúa en espacio *display-referred* (el mismo en el
    que se ven las curvas de un revelador): por eso se aplica después de la
    respuesta de la emulsión y antes del grano.

    Canales:
      - ``rgb``: curva maestra sobre R, G y B.
      - ``r`` / ``g`` / ``b``: curva por canal.
      - ``l``: curva de luminancia; se reescala el RGB proporcionalmente para
        conservar el tono (el matiz no debe cambiar al mover la curva).
    """
    if not isinstance(curve_spec, dict) or not curve_spec:
        return display

    out = display
    # Curva maestra: se aplica sobre los tres canales.
    master = build_curve_lut(curve_spec.get("rgb"))
    if master is not None:
        idx = np.clip((out * 255.0).astype(np.int32), 0, 255)
        out = master[idx]

    # Curvas por canal (r, g, b).
    for i, key in enumerate(("r", "g", "b")):
        lut = build_curve_lut(curve_spec.get(key))
        if lut is None:
            continue
        chan = out[..., i]
        idx = np.clip((chan * 255.0).astype(np.int32), 0, 255)
        out[..., i] = lut[idx]

    # Curva de luminancia: se preserva el matiz escalando los tres canales.
    lut = build_curve_lut(curve_spec.get("l"))
    if lut is not None:
        luma = np.sum(out * LUMA, axis=-1, keepdims=True)
        idx = np.clip((luma * 255.0).astype(np.int32), 0, 255)
        new_luma = lut[idx]
        # Cuando el negro es 0 la división no vale: se deja esa zona quieta.
        scale = np.where(luma > 1e-4, new_luma / np.maximum(luma, 1e-4), 1.0)
        out = out * scale

    return out


def shift_hues(rgb, hue_rules):
    """Shift selective hues (e.g. skin tones, greens, skies)."""
    y = np.sum(rgb * LUMA, axis=-1, keepdims=True)
    cb = (rgb[..., 2:3] - y) / 1.8556
    cr = (rgb[..., 0:1] - y) / 1.5748
    h = np.arctan2(cr, cb)
    c = np.sqrt(cb * cb + cr * cr)
    gate = np.clip(c / 0.04, 0.0, 1.0)

    dh = np.zeros_like(h)
    cm = np.ones_like(c)
    sigma = 35.0 * math.pi / 180.0

    for from_name, to_name, amt, chroma in hue_rules:
        from_idx = HUE_NAMES.index(from_name)
        to_idx = HUE_NAMES.index(to_name)
        hs = HUE_ANGLES[from_idx]
        d = wrap_angle(h - hs) / sigma
        w = np.exp(-0.5 * d * d) * gate
        if from_idx != to_idx:
            target_diff = wrap_angle(HUE_ANGLES[to_idx] - hs)
            dh += w * amt * target_diff
        cm *= 1.0 + w * (chroma - 1.0)

    h_new = h + dh
    c_new = c * cm

    cr_new = c_new * np.sin(h_new)
    cb_new = c_new * np.cos(h_new)

    r = y + cr_new * 1.5748
    b = y + cb_new * 1.8556
    g = (y - LUMA[0] * r - LUMA[2] * b) / LUMA[1]

    return np.clip(np.concatenate([r, g, b], axis=-1), 0.0, 1.0)


RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef"}
HEIF_EXTENSIONS = {".heic", ".heif"}


@functools.lru_cache(maxsize=1)
def _get_srgb_icc_bytes() -> bytes:
    """Return canonical sRGB IEC61966-2.1 ICC profile bytes for tagged color-managed exports."""
    prof = ImageCms.createProfile("sRGB")
    return ImageCms.ImageCmsProfile(prof).tobytes()


def get_srgb_icc_bytes() -> bytes:
    """Public accessor for the cached canonical sRGB IEC61966-2.1 ICC profile payload."""
    return _get_srgb_icc_bytes()


def _is_srgb_icc_profile(icc_bytes: bytes | None) -> bool:
    """Return True when ICC bytes are missing or already represent an sRGB color space."""
    if not icc_bytes:
        return True
    try:
        desc = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))) or ""
        return "srgb" in desc.lower()
    except Exception:
        return False


def _convert_pil_to_srgb(pil_img: Image.Image, icc_bytes: bytes | None) -> Image.Image:
    """Convert a PIL image with an arbitrary embedded ICC profile (Adobe RGB, Display P3, ProPhoto) to sRGB."""
    if not icc_bytes or _is_srgb_icc_profile(icc_bytes):
        return pil_img.convert("RGB")
    try:
        src_prof = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
        dst_prof = ImageCms.createProfile("sRGB")
        src_img = pil_img if pil_img.mode in ("RGB", "L", "CMYK") else pil_img.convert("RGB")
        converted = ImageCms.profileToProfile(
            src_img,
            src_prof,
            dst_prof,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )
        return converted if converted is not None else pil_img.convert("RGB")
    except Exception:
        return pil_img.convert("RGB")


@functools.lru_cache(maxsize=8)
def _build_icc_to_srgb_lut(icc_bytes: bytes, grid_size: int = 33) -> np.ndarray | None:
    """Build and cache a 33x33x33 trilinear ICC-to-sRGB LUT preserving continuous 16-bit float gradation."""
    try:
        src_prof = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
        dst_prof = ImageCms.createProfile("sRGB")
        grid_1d = np.rint(np.linspace(0, 255, grid_size)).astype(np.uint8)
        rr, gg, bb = np.meshgrid(grid_1d, grid_1d, grid_1d, indexing="ij")
        flat = np.stack([rr, gg, bb], axis=-1).reshape(-1, 1, 3)
        lut_img = ImageCms.profileToProfile(
            Image.fromarray(flat, mode="RGB"),
            src_prof,
            dst_prof,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
        )
        if lut_img is None:
            return None
        return (np.asarray(lut_img, dtype=np.float32) / 255.0).reshape(grid_size, grid_size, grid_size, 3)
    except Exception:
        return None


def _convert_float32_icc_to_srgb(arr_rgb: np.ndarray, icc_bytes: bytes | None) -> np.ndarray:
    """Convert float32 [0..1] RGB pixels from an embedded wide-gamut ICC profile into sRGB [0..1]."""
    if not icc_bytes or _is_srgb_icc_profile(icc_bytes):
        return arr_rgb
    lut = _build_icc_to_srgb_lut(bytes(icc_bytes))
    if lut is None:
        return arr_rgb
    n = lut.shape[0]
    coords = np.stack(
        [
            np.clip(arr_rgb[..., 0], 0.0, 1.0),
            np.clip(arr_rgb[..., 1], 0.0, 1.0),
            np.clip(arr_rgb[..., 2], 0.0, 1.0),
        ],
        axis=0,
    ) * float(n - 1)
    out = np.stack(
        [scipy.ndimage.map_coordinates(lut[..., c], coords, order=1, mode="nearest") for c in range(3)],
        axis=-1,
    )
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def _to_ascii_transliterated(text: str) -> str:
    """Transliterate accented Latin characters (e.g. 'Película' -> 'Pelicula') for strict ASCII EXIF/TIFF tags."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return normalized.encode("ascii", errors="ignore").decode("ascii").strip()


def _open_heif_fallback_macos(path: Path) -> Image.Image:
    """Decode HEIC/HEIF on macOS via native ImageIO (`sips`) when `pillow-heif` is absent."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_png = Path(tmp.name)
    try:
        subprocess.run(
            ["sips", "-s", "format", "png", str(path), "--out", str(tmp_png)],
            capture_output=True,
            check=True,
            timeout=30,
        )
        with Image.open(tmp_png) as decoded:
            icc_bytes = decoded.info.get("icc_profile")
            return _convert_pil_to_srgb(decoded, icc_bytes)
    finally:
        tmp_png.unlink(missing_ok=True)


def _resize_float32_rgb(arr, max_dim):
    """Downscale float32 RGB [H, W, 3] preserving full 32-bit dynamic range."""
    h, w = arr.shape[:2]
    if max_dim is None or max(h, w) <= max_dim:
        return arr
    scale = max_dim / float(max(h, w))
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    channels = [
        np.asarray(
            Image.fromarray(np.ascontiguousarray(arr[..., c], dtype=np.float32)).resize(
                new_size, Image.Resampling.BICUBIC
            ),
            dtype=np.float32
        )
        for c in range(3)
    ]
    return np.stack(channels, axis=-1)


@functools.lru_cache(maxsize=6)
def _load_image_linear_cached(resolved_path_str, mtime_ns, max_dim):
    """LRU-cached linear RGB loader for instant slider responsiveness.

    The cache holds complete float32 arrays, so a large ``max_dim`` costs
    hundreds of megabytes per entry. It is therefore restricted to preview
    sizes; full-resolution development always decodes straight from disk.
    """
    return _decode_image_linear_uncached(Path(resolved_path_str), max_dim=max_dim)


def _cacheable_preview(max_dim) -> bool:
    """Only preview-sized decodes are worth keeping in the LRU cache."""
    return max_dim is not None and int(max_dim) <= 1600


def _decode_image_linear_uncached(path, max_dim=None):
    """Decodes 16-bit RAW or standard image into scene-linear float32 RGB [0..1+]."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in RAW_EXTENSIONS:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            # Use half_size fast demosaic when previewing <= 1600px if full sensor is huge
            use_half = bool(max_dim is not None and max_dim <= 1400 and max(raw.sizes.width, raw.sizes.height) >= 2800)
            rgb16 = raw.postprocess(
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=16,
                use_camera_wb=True,
                no_auto_bright=True,
                half_size=use_half,
                user_black=raw.black_level_per_channel[0] if raw.black_level_per_channel else None
            )
            arr_srgb = rgb16.astype(np.float32) / 65535.0
            arr_srgb = _resize_float32_rgb(arr_srgb, max_dim)
            return srgb_to_linear(arr_srgb)

    try:
        src_ctx = Image.open(path)
    except OSError:
        if suffix in HEIF_EXTENSIONS and is_macos():
            img = _open_heif_fallback_macos(path)
            if max_dim is not None and max(img.size) > max_dim:
                scale = max_dim / float(max(img.size))
                new_size = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            arr_srgb = np.asarray(img, dtype=np.float32) / 255.0
            return srgb_to_linear(arr_srgb)
        raise

    with src_ctx as src:
        src_icc = src.info.get("icc_profile")
        if not src_icc and hasattr(src, "tag_v2"):
            raw_icc_tag = src.tag_v2.get(34675)
            if isinstance(raw_icc_tag, (bytes, bytearray)):
                src_icc = bytes(raw_icc_tag)

        if suffix in (".tif", ".tiff"):
            arr16_rgb = _try_read_tiff16_rgb(path, src)
            if arr16_rgb is not None:
                arr16_rgb = _convert_float32_icc_to_srgb(arr16_rgb, src_icc)
                arr_srgb = _resize_float32_rgb(arr16_rgb, max_dim)
                return srgb_to_linear(arr_srgb)

        img = ImageOps.exif_transpose(src)
        if img.mode in ("I;16", "I;16L", "I;16B", "I"):
            arr16 = np.asarray(img, dtype=np.float32)
            max_v = _declared_16bit_scale(img, src)
            gray = np.clip(arr16 / max_v, 0.0, 1.0)
            arr_srgb = np.stack([gray, gray, gray], axis=-1)
            arr_srgb = _resize_float32_rgb(arr_srgb, max_dim)
            return srgb_to_linear(arr_srgb)

        img = _convert_pil_to_srgb(img, src_icc)
        if max_dim is not None and max(img.size) > max_dim:
            scale = max_dim / float(max(img.size))
            new_size = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        arr_srgb = np.asarray(img, dtype=np.float32) / 255.0
        return srgb_to_linear(arr_srgb)


def _declared_16bit_scale(img, src=None) -> float:
    """Return the correct full-scale value for a monochrome image with a declared 16-bit depth.

    The scale MUST be derived from the *declared* bit depth, never from the image
    content. A sub-exposed 16-bit film scan routinely stays entirely below 255;
    scaling it by 255 instead of 65535 crushes the image by a factor of ~187 and
    the error is unrecoverable afterwards because the clipping already happened
    in the decoder.
    """
    if img.mode in ("I;16", "I;16L", "I;16B"):
        return 65535.0
    tags = getattr(src if src is not None else img, "tag_v2", None)
    if tags:
        bps = tags.get(258)
        if isinstance(bps, (tuple, list)):
            bps = bps[0] if bps else None
        if bps == 16:
            return 65535.0
    # 32-bit integer container without a declared depth: fall back to content range.
    arr = np.asarray(img)
    return 65535.0 if float(arr.max()) > 255.0 else 255.0


def _try_read_tiff16_rgb(path: Path, pil_src: Image.Image):
    """Losslessly decode 48-bit (16, 16, 16) RGB TIFF strips into float32 [0..1] when uncompressed/deflate."""
    try:
        tags = getattr(pil_src, "tag_v2", None)
        if not tags:
            return None
        bps = tags.get(258)
        if tuple(bps or ())[:3] != (16, 16, 16):
            return None
        compression = int(tags.get(259, 1))
        planar = int(tags.get(284, 1))
        predictor = int(tags.get(317, 1))
        if planar != 1 or compression not in (1, 8, 32946):
            return None

        w, h = pil_src.size
        spp = len(bps)
        offsets = tags.get(273)
        byte_counts = tags.get(279)
        if not offsets or not byte_counts:
            return None
        if isinstance(offsets, int):
            offsets = (offsets,)
        if isinstance(byte_counts, int):
            byte_counts = (byte_counts,)

        with open(path, "rb") as f:
            head = f.read(2)
            endian = "<" if head == b"II" else ">"
            raw_chunks = []
            for off, bc in zip(offsets, byte_counts, strict=False):
                f.seek(int(off))
                chunk = f.read(int(bc))
                if compression in (8, 32946):
                    chunk = zlib.decompress(chunk)
                raw_chunks.append(chunk)

        buf = b"".join(raw_chunks)
        expected = h * w * spp * 2
        if len(buf) < expected:
            return None
        arr = np.frombuffer(buf[:expected], dtype=f"{endian}u2").reshape(h, w, spp)
        if predictor == 2:
            arr = np.cumsum(arr, axis=1, dtype=np.uint16)
        rgb = arr[..., :3].astype(np.float32) / 65535.0
        orient = int(tags.get(274, 1))
        if orient == 3:
            rgb = np.rot90(rgb, 2)
        elif orient == 6:
            rgb = np.rot90(rgb, -1)
        elif orient == 8:
            rgb = np.rot90(rgb, 1)
        return np.clip(np.ascontiguousarray(rgb), 0.0, 1.0)
    except Exception:
        return None


def normalize_crop_rect(crop_rect) -> tuple[float, float, float, float] | None:
    """Normalize [x, y, w, h] crop rectangle in [0..1]; returns None when full-frame."""
    if crop_rect is None:
        return None
    if isinstance(crop_rect, dict):
        raw = (crop_rect.get("x", 0.0), crop_rect.get("y", 0.0), crop_rect.get("w", 1.0), crop_rect.get("h", 1.0))
    elif isinstance(crop_rect, (list, tuple)) and len(crop_rect) == 4:
        raw = tuple(crop_rect)
    else:
        return None
    try:
        x, y, w, h = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return None
    x = max(0.0, min(0.98, x))
    y = max(0.0, min(0.98, y))
    w = max(0.02, min(1.0 - x, w))
    h = max(0.02, min(1.0 - y, h))
    if x <= 1e-4 and y <= 1e-4 and w >= 0.9998 and h >= 0.9998:
        return None
    return (x, y, w, h)


def inscribed_crop_for_angle(w: int, h: int, angle_deg: float) -> tuple[float, float, float, float]:
    """Return normalized (x, y, w, h) of largest axis-aligned rectangle inside rotated frame."""
    if w <= 0 or h <= 0:
        return (0.0, 0.0, 1.0, 1.0)
    theta = abs(math.radians(float(angle_deg)))
    if theta < 1e-5:
        return (0.0, 0.0, 1.0, 1.0)
    quad_wide = w >= h
    side_long, side_short = (float(w), float(h)) if quad_wide else (float(h), float(w))
    sin_a = math.sin(theta)
    cos_a = math.cos(theta)
    if side_short <= 2.0 * sin_a * cos_a * side_long:
        x_s = 0.5 * side_short
        wr, hr = (x_s / sin_a, x_s / cos_a) if quad_wide else (x_s / cos_a, x_s / sin_a)
    else:
        cos_2a = max(1e-5, cos_a * cos_a - sin_a * sin_a)
        wr = (w * cos_a - h * sin_a) / cos_2a
        hr = (h * cos_a - w * sin_a) / cos_2a
    wr = max(4.0, min(float(w), wr))
    hr = max(4.0, min(float(h), hr))
    return ((w - wr) / (2.0 * w), (h - hr) / (2.0 * h), wr / float(w), hr / float(h))


def _apply_perspective_and_straighten(
    arr: np.ndarray,
    straighten: float = 0.0,
    keystone_v: float = 0.0,
    keystone_h: float = 0.0,
) -> np.ndarray:
    """Apply fine rotation (straighten) and vertical/horizontal perspective in linear float32."""
    h, w = arr.shape[:2]
    if h < 4 or w < 4:
        return arr

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    half_w = w * 0.5
    half_h = h * 0.5
    u = (xx - half_w) / max(1.0, half_w)
    v = (yy - half_h) / max(1.0, half_h)

    kv = math.radians(max(-30.0, min(30.0, float(keystone_v)))) * 0.65
    kh = math.radians(max(-30.0, min(30.0, float(keystone_h)))) * 0.65
    if abs(kv) > 1e-4 or abs(kh) > 1e-4:
        denom = np.maximum(0.25, 1.0 + kv * v + kh * u)
        u = u / denom
        v = v / denom

    dx = u * half_w
    dy = v * half_h
    rad = math.radians(-float(straighten))
    if abs(rad) > 1e-5:
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        src_x = half_w + dx * cos_a - dy * sin_a
        src_y = half_h + dx * sin_a + dy * cos_a
    else:
        src_x = half_w + dx
        src_y = half_h + dy

    coords = np.array([src_y, src_x], dtype=np.float32)
    channels = [
        scipy.ndimage.map_coordinates(arr[..., c], coords, order=1, mode="nearest")
        for c in range(arr.shape[2])
    ]
    return np.stack(channels, axis=-1).astype(np.float32)


def apply_geometry(
    arr,
    rotate=0,
    flip_h=False,
    flip_v=False,
    straighten=0.0,
    keystone_v=0.0,
    keystone_h=0.0,
    crop_rect=None,
    auto_crop_straighten=True,
):
    """Apply 90-degree rotations, horizontal/vertical mirror, straighten, perspective, and crop."""
    out = arr
    rot = int(rotate or 0) % 360
    if rot == 90:
        out = np.rot90(out, k=-1, axes=(0, 1))
    elif rot == 180:
        out = np.rot90(out, k=2, axes=(0, 1))
    elif rot == 270:
        out = np.rot90(out, k=1, axes=(0, 1))
    if flip_h:
        out = np.fliplr(out)
    if flip_v:
        out = np.flipud(out)

    str_deg = max(-45.0, min(45.0, float(straighten or 0.0)))
    kv_deg = max(-30.0, min(30.0, float(keystone_v or 0.0)))
    kh_deg = max(-30.0, min(30.0, float(keystone_h or 0.0)))
    if abs(str_deg) > 0.01 or abs(kv_deg) > 0.01 or abs(kh_deg) > 0.01:
        out = _apply_perspective_and_straighten(out, straighten=str_deg, keystone_v=kv_deg, keystone_h=kh_deg)

    norm_crop = normalize_crop_rect(crop_rect)
    if norm_crop is None and auto_crop_straighten and abs(str_deg) > 0.01:
        h, w = out.shape[:2]
        norm_crop = inscribed_crop_for_angle(w, h, str_deg)

    if norm_crop is not None:
        h, w = out.shape[:2]
        cx, cy, cw, ch = norm_crop
        x0 = max(0, min(w - 4, int(round(cx * w))))
        y0 = max(0, min(h - 4, int(round(cy * h))))
        x1 = max(x0 + 4, min(w, int(round((cx + cw) * w))))
        y1 = max(y0 + 4, min(h, int(round((cy + ch) * h))))
        out = out[y0:y1, x0:x1]

    return np.ascontiguousarray(out)


def load_image_linear(
    path,
    max_dim=None,
    rotate=0,
    flip_h=False,
    flip_v=False,
    straighten=0.0,
    keystone_v=0.0,
    keystone_h=0.0,
    crop_rect=None,
    auto_crop_straighten=True,
):
    """Loads a RAW or standard image into scene-linear float32 RGB, utilizing RAM cache for previews."""
    path = Path(path).resolve()
    if max_dim is not None and path.is_file() and _cacheable_preview(max_dim):
        mtime_ns = path.stat().st_mtime_ns
        base = _load_image_linear_cached(str(path), mtime_ns, int(max_dim)).copy()
    else:
        base = _decode_image_linear_uncached(path, max_dim=max_dim)
    if (
        rotate
        or flip_h
        or flip_v
        or abs(float(straighten or 0.0)) > 0.01
        or abs(float(keystone_v or 0.0)) > 0.01
        or abs(float(keystone_h or 0.0)) > 0.01
        or normalize_crop_rect(crop_rect) is not None
    ):
        base = apply_geometry(
            base,
            rotate=rotate,
            flip_h=flip_h,
            flip_v=flip_v,
            straighten=straighten,
            keystone_v=keystone_v,
            keystone_h=keystone_h,
            crop_rect=crop_rect,
            auto_crop_straighten=auto_crop_straighten,
        )
    return base


def format_analog_caption(analog_meta: dict | None) -> str:
    """Format human-readable archival analog film caption from structured roll metadata."""
    if not isinstance(analog_meta, dict):
        return ""
    clean = {k: str(v).strip() for k, v in analog_meta.items() if v is not None and str(v).strip()}
    if not clean:
        return ""

    parts: list[str] = []
    cam = " ".join(p for p in (clean.get("camera_make", ""), clean.get("camera_model", "")) if p).strip()
    if cam:
        parts.append(cam)
    if clean.get("lens"):
        parts.append(clean["lens"])

    stock_bits: list[str] = []
    if clean.get("film_stock"):
        stock_bits.append(clean["film_stock"])
    if clean.get("film_format"):
        stock_bits.append(f"({clean['film_format']})")
    if clean.get("shot_iso"):
        iso_s = clean["shot_iso"]
        stock_bits.append(f"@ ISO {iso_s}" if not iso_s.upper().startswith("ISO") else f"@ {iso_s}")
    if stock_bits:
        parts.append(" ".join(stock_bits))

    if clean.get("dev_process"):
        parts.append(clean["dev_process"])
    if clean.get("scanner"):
        parts.append(f"Scan: {clean['scanner']}")
    if clean.get("notes"):
        parts.append(clean["notes"])

    return " | ".join(parts)


_SAFE_IFD0_TAGS = {
    0x010F,  # Make
    0x0110,  # Model
    0x0132,  # DateTime
    0x013B,  # Artist
    0x8298,  # Copyright
}

_SAFE_EXIF_SUBIFD_TAGS = {
    0x829A,  # ExposureTime
    0x829D,  # FNumber
    0x8822,  # ExposureProgram
    0x8827,  # ISOSpeedRatings
    0x9000,  # ExifVersion
    0x9003,  # DateTimeOriginal
    0x9004,  # DateTimeDigitized
    0x9201,  # ShutterSpeedValue
    0x9202,  # ApertureValue
    0x9204,  # ExposureBiasValue
    0x9207,  # MeteringMode
    0x9209,  # Flash
    0x920A,  # FocalLength
    0xA405,  # FocalLengthIn35mmFilm
    0xA430,  # CameraOwnerName
    0xA432,  # LensSpecification
    0xA433,  # LensMake
    0xA434,  # LensModel
}


def build_export_exif_bytes(source_path=None, analog_meta: dict | None = None) -> bytes | None:
    """Build normalized EXIF payload preserving safe archival source tags (including RAW) and analog EXIF fields."""
    exif = Image.Exif()
    has_data = True

    if source_path:
        try:
            src_p = Path(source_path)
            if src_p.is_file():
                with Image.open(src_p) as im:
                    src_exif = im.getexif()
                    if src_exif:
                        for tag_id in _SAFE_IFD0_TAGS:
                            if tag_id in src_exif and src_exif[tag_id] not in (None, ""):
                                exif[tag_id] = src_exif[tag_id]
                        src_sub = src_exif.get_ifd(0x8769)
                        if src_sub:
                            dst_sub = exif.get_ifd(0x8769)
                            for tag_id in _SAFE_EXIF_SUBIFD_TAGS:
                                if tag_id in src_sub and src_sub[tag_id] not in (None, ""):
                                    dst_sub[tag_id] = src_sub[tag_id]
        except Exception as exc:
            logger.warning("No se pudo copiar el EXIF de origen: %s", exc)

    exif[0x0112] = 1  # Orientation normalized to top-left
    exif[0x0131] = f"Haluro {__version__}"
    sub_ifd = exif.get_ifd(0x8769)
    sub_ifd[0xA001] = 1  # ColorSpace = sRGB

    if isinstance(analog_meta, dict):
        clean = {k: str(v).strip() for k, v in analog_meta.items() if v is not None and str(v).strip()}
        if clean:
            if clean.get("camera_make"):
                mk = _to_ascii_transliterated(clean["camera_make"])
                if mk:
                    exif[0x010F] = mk
            if clean.get("camera_model"):
                md = _to_ascii_transliterated(clean["camera_model"])
                if md:
                    exif[0x0110] = md
            if clean.get("photographer"):
                art = _to_ascii_transliterated(clean["photographer"])
                if art:
                    exif[0x013B] = art

            caption = format_analog_caption(clean)
            if caption:
                # Standard TIFF/EXIF ASCII description (transliterated safely to preserve accented Spanish words)
                ascii_desc = _to_ascii_transliterated(caption)
                if ascii_desc:
                    exif[0x010E] = ascii_desc

            if clean.get("lens"):
                ln = _to_ascii_transliterated(clean["lens"])
                if ln:
                    sub_ifd[0xA434] = ln
            if clean.get("shot_iso"):
                digits = "".join(ch for ch in clean["shot_iso"] if ch.isdigit())
                if digits:
                    iso_int = int(digits)
                    if 1 <= iso_int <= 65535:
                        sub_ifd[0x8827] = iso_int
            if caption:
                sub_ifd[0x9286] = b"UNICODE\x00" + caption.encode("utf-16-le")

    if not has_data:
        return None
    try:
        return exif.tobytes()
    except Exception:
        return None


def extract_clean_exif(path):
    """Extracts source EXIF bytes with Orientation normalized to 1 (top-left) so viewers don't double-rotate."""
    return build_export_exif_bytes(source_path=path, analog_meta=None)


def _write_tiff_container(
    u16: np.ndarray,
    target_path: Path,
    photometric: int = 2,
    analog_meta: dict | None = None,
    icc_bytes: bytes | None = None,
    extra_tags: list[tuple[int, int, int, bytes]] | None = None,
) -> None:
    """Write a 16-bit/channel RGB TIFF 6.0 / TIFF-EP container with Adobe Deflate strips."""
    u16 = np.ascontiguousarray(u16)
    h, w = u16.shape[:2]
    rows_per_strip = max(1, min(h, 64))
    strip_blobs: list[bytes] = []
    for y0 in range(0, h, rows_per_strip):
        strip_arr = u16[y0 : min(h, y0 + rows_per_strip)]
        strip_blobs.append(zlib.compress(strip_arr.tobytes(), level=6))

    num_strips = len(strip_blobs)
    clean_meta = (
        {k: str(v).strip() for k, v in analog_meta.items() if v is not None and str(v).strip()}
        if isinstance(analog_meta, dict)
        else {}
    )
    caption = format_analog_caption(clean_meta)

    def _ascii_bytes(text: str) -> bytes:
        clean_ascii = _to_ascii_transliterated(text)
        return clean_ascii.encode("ascii", errors="ignore") + b"\x00"

    raw_tags: list[tuple[int, int, int, bytes]] = [
        (256, 4, 1, struct.pack("<I", w)),  # ImageWidth
        (257, 4, 1, struct.pack("<I", h)),  # ImageLength
        (258, 3, 3, struct.pack("<HHH", 16, 16, 16)),  # BitsPerSample = (16, 16, 16)
        (259, 3, 1, struct.pack("<H", 8)),  # Compression = 8 (Adobe Deflate)
        (262, 3, 1, struct.pack("<H", photometric)),
    ]
    if caption:
        ab = _ascii_bytes(caption)
        raw_tags.append((270, 2, len(ab), ab))  # ImageDescription
    if clean_meta.get("camera_make"):
        ab = _ascii_bytes(clean_meta["camera_make"])
        raw_tags.append((271, 2, len(ab), ab))  # Make
    if clean_meta.get("camera_model"):
        ab = _ascii_bytes(clean_meta["camera_model"])
        raw_tags.append((272, 2, len(ab), ab))  # Model

    raw_tags.extend(
        [
            (273, 4, num_strips, b"\x00" * (4 * num_strips)),  # StripOffsets
            (274, 3, 1, struct.pack("<H", 1)),  # Orientation = 1
            (277, 3, 1, struct.pack("<H", 3)),  # SamplesPerPixel = 3
            (278, 4, 1, struct.pack("<I", rows_per_strip)),  # RowsPerStrip
            (279, 4, num_strips, struct.pack(f"<{num_strips}I", *[len(b) for b in strip_blobs])),
            (282, 5, 1, struct.pack("<II", 300, 1)),  # XResolution = 300 DPI
            (283, 5, 1, struct.pack("<II", 300, 1)),  # YResolution = 300 DPI
            (284, 3, 1, struct.pack("<H", 1)),  # PlanarConfiguration = 1 (Chunky)
            (296, 3, 1, struct.pack("<H", 2)),  # ResolutionUnit = Inch
        ]
    )
    sw_b = _ascii_bytes(f"Haluro {__version__}")
    raw_tags.append((305, 2, len(sw_b), sw_b))  # Software
    if clean_meta.get("photographer"):
        ab = _ascii_bytes(clean_meta["photographer"])
        raw_tags.append((315, 2, len(ab), ab))  # Artist
    if icc_bytes:
        raw_tags.append((34675, 7, len(icc_bytes), icc_bytes))
    if extra_tags:
        raw_tags.extend(extra_tags)

    raw_tags.sort(key=lambda item: item[0])
    num_entries = len(raw_tags)
    ifd_offset = 8
    extra_start = ifd_offset + 2 + num_entries * 12 + 4

    probe_cursor = extra_start
    for _tag, _typ, _cnt, val_b in raw_tags:
        if len(val_b) > 4:
            probe_cursor += len(val_b) + (len(val_b) % 2)
    strips_start = probe_cursor

    strip_offsets: list[int] = []
    cur_strip_off = strips_start
    for blob in strip_blobs:
        strip_offsets.append(cur_strip_off)
        cur_strip_off += len(blob)

    final_tags: list[tuple[int, int, int, bytes]] = []
    for tag, typ, cnt, val_b in raw_tags:
        if tag == 273:
            val_b = struct.pack(f"<{num_strips}I", *strip_offsets)
        final_tags.append((tag, typ, cnt, val_b))

    ifd_buf = bytearray()
    ifd_buf += struct.pack("<H", num_entries)
    extra_buf = bytearray()

    for tag, typ, cnt, val_b in final_tags:
        if len(val_b) <= 4:
            inline = val_b + b"\x00" * (4 - len(val_b))
            ifd_buf += struct.pack("<HHI", tag, typ, cnt) + inline
        else:
            ptr = extra_start + len(extra_buf)
            ifd_buf += struct.pack("<HHII", tag, typ, cnt, ptr)
            extra_buf += val_b
            if len(val_b) % 2:
                extra_buf += b"\x00"

    ifd_buf += struct.pack("<I", 0)  # Next IFD = 0

    with open(target_path, "wb") as f:
        f.write(b"II\x2a\x00\x08\x00\x00\x00")
        f.write(ifd_buf)
        f.write(extra_buf)
        for blob in strip_blobs:
            f.write(blob)


def save_tiff_16bit_rgb(float_srgb: np.ndarray, target_path: Path, analog_meta: dict | None = None) -> None:
    """Write a true 48-bit (16-bit per channel uint16 RGB) lossless Adobe-Deflate archival TIFF."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    u16 = np.clip(np.rint(np.clip(float_srgb, 0.0, 1.0) * 65535.0), 0, 65535).astype("<u2")
    _write_tiff_container(
        u16,
        target_path,
        photometric=2,
        analog_meta=analog_meta,
        icc_bytes=_get_srgb_icc_bytes(),
    )


def save_linear_dng_16bit(float_srgb: np.ndarray, target_path: Path, analog_meta: dict | None = None) -> None:
    """Write a 16-bit Linear DNG (TIFF-EP LinearRaw) preserving full 16-bit tonal headroom."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lin = srgb_to_linear(np.clip(float_srgb, 0.0, 1.0))
    u16 = np.clip(np.rint(np.clip(lin, 0.0, 1.0) * 65535.0), 0, 65535).astype("<u2")

    # XYZ D65 -> linear sRGB matrix (DNG ColorMatrix1 maps XYZ to camera/linear space)
    xyz_to_srgb = (
        (3.2406, -1.5372, -0.4986),
        (-0.9689, 1.8758, 0.0415),
        (0.0557, -0.2040, 1.0570),
    )
    cm1_bytes = b"".join(
        struct.pack("<ii", int(round(val * 10000)), 10000)
        for row in xyz_to_srgb
        for val in row
    )
    as_shot_neutral = struct.pack("<IIIIII", 1, 1, 1, 1, 1, 1)
    model_str = "Haluro Digital Darkroom"
    if isinstance(analog_meta, dict) and analog_meta.get("camera_model"):
        model_str = f"{analog_meta.get('camera_make', '')} {analog_meta['camera_model']}".strip()
    model_bytes = _to_ascii_transliterated(model_str).encode("ascii", errors="ignore") + b"\x00"

    dng_tags: list[tuple[int, int, int, bytes]] = [
        (254, 4, 1, struct.pack("<I", 0)),  # NewSubfileType = 0 (Full-resolution image)
        (50706, 1, 4, struct.pack("<BBBB", 1, 4, 0, 0)),  # DNGVersion = 1.4.0.0
        (50707, 1, 4, struct.pack("<BBBB", 1, 1, 0, 0)),  # DNGBackwardVersion = 1.1.0.0
        (50708, 2, len(model_bytes), model_bytes),  # UniqueCameraModel
        (50721, 10, 9, cm1_bytes),  # ColorMatrix1 (SRATIONAL[9])
        (50728, 5, 3, as_shot_neutral),  # AsShotNeutral (RATIONAL[3])
        (50778, 3, 1, struct.pack("<H", 21)),  # CalibrationIlluminant1 = D65 (21)
    ]
    _write_tiff_container(
        u16,
        target_path,
        photometric=34892,  # LinearRaw
        analog_meta=analog_meta,
        icc_bytes=None,
        extra_tags=dng_tags,
    )


def resolve_export_extension(fmt_str: str | None, source_path: Path | str | None = None) -> str:
    """Resolve output extension from format selector ('original', 'dng', 'tiff', 'png', 'jpg')."""
    fmt = str(fmt_str or "jpg").strip().lower().lstrip(".")
    if fmt == "original":
        if source_path is not None:
            src_ext = Path(source_path).suffix.lower()
            if src_ext in (".jpg", ".jpeg"):
                return ".jpg"
            if src_ext == ".png":
                return ".png"
            if src_ext in (".tif", ".tiff"):
                return ".tiff"
            if src_ext == ".webp":
                return ".webp"
            if src_ext == ".dng" or src_ext in RAW_EXTENSIONS:
                return ".dng"
            if src_ext in HEIF_EXTENSIONS:
                return ".tiff"
        return ".tiff"
    mapping = {
        "jpg": ".jpg",
        "jpeg": ".jpg",
        "png": ".png",
        "tif": ".tiff",
        "tiff": ".tiff",
        "dng": ".dng",
        "webp": ".webp",
    }
    return mapping.get(fmt, ".jpg")


def write_geometry_xmp_sidecar(
    target_path: Path,
    rotate: int = 0,
    flip_h: bool = False,
    flip_v: bool = False,
    straighten: float = 0.0,
    crop_rect=None,
) -> Path:
    """Write a standard non-destructive XMP sidecar describing crop, straighten, and orientation."""
    target_path = Path(target_path)
    xmp_path = target_path.with_suffix(".xmp")
    norm_crop = normalize_crop_rect(crop_rect)
    if norm_crop is not None:
        cx, cy, cw, ch = norm_crop
        has_crop = "True"
        left, top, right, bottom = cx, cy, cx + cw, cy + ch
    else:
        has_crop = "False"
        left, top, right, bottom = 0.0, 0.0, 1.0, 1.0

    rot = int(rotate or 0) % 360
    orient_map = {
        (0, False, False): 1,
        (0, True, False): 2,
        (180, False, False): 3,
        (0, False, True): 4,
        (90, True, False): 5,
        (90, False, False): 6,
        (270, True, False): 7,
        (270, False, False): 8,
    }
    tiff_orient = orient_map.get((rot, bool(flip_h), bool(flip_v)), 1)
    angle = round(max(-45.0, min(45.0, float(straighten or 0.0))), 3)

    xmp_body = f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Haluro {__version__}">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:tiff="http://ns.adobe.com/tiff/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    tiff:Orientation="{tiff_orient}"
    crs:Version="15.0"
    crs:HasCrop="{has_crop}"
    crs:CropLeft="{left:.6f}"
    crs:CropTop="{top:.6f}"
    crs:CropRight="{right:.6f}"
    crs:CropBottom="{bottom:.6f}"
    crs:CropAngle="{angle:.3f}" />
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""
    xmp_path.write_text(xmp_body, encoding="utf-8")
    return xmp_path


EASEL_BORDERS = ("none", "white_thin", "white_gallery", "gallery_caption", "black_rebate")


def extract_source_exif(file_path: Path | str) -> dict[str, str]:
    """Read key capture EXIF fields (camera, lens, focal, aperture, shutter, ISO, date) safely."""
    path = Path(file_path)
    if not path.is_file():
        return {}
    info: dict[str, str] = {}
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return {}
            make = str(exif.get(271) or "").strip()
            model = str(exif.get(272) or "").strip()
            if model:
                if make and not model.lower().startswith(make.lower()):
                    info["camera"] = f"{make} {model}"
                else:
                    info["camera"] = model
            elif make:
                info["camera"] = make

            sub = {}
            try:
                sub = exif.get_ifd(0x8769) or {}
            except Exception:
                sub = {}

            lens = str(sub.get(42036) or "").strip()
            if lens:
                info["lens"] = lens

            focal = sub.get(37386)
            if focal:
                try:
                    f_val = float(focal)
                    if f_val > 0:
                        info["focal"] = f"{int(round(f_val))}mm"
                except (TypeError, ValueError):
                    logger.debug("EXIF focal no numérico en %s", path.name)

            fnum = sub.get(33437)
            if fnum:
                try:
                    fn = float(fnum)
                    if fn > 0:
                        info["aperture"] = f"f/{fn:.1f}".replace(".0", "")
                except (TypeError, ValueError):
                    logger.debug("EXIF apertura no numérica en %s", path.name)

            exp = sub.get(33434)
            if exp:
                try:
                    et = float(exp)
                    if 0 < et < 1.0:
                        info["shutter"] = f"1/{int(round(1.0 / et))}s"
                    elif et >= 1.0:
                        info["shutter"] = f"{et:.1f}s".replace(".0s", "s")
                except (TypeError, ValueError):
                    logger.debug("EXIF obturación no numérica en %s", path.name)

            iso = sub.get(34855)
            if iso:
                if isinstance(iso, (tuple, list)) and iso:
                    iso = iso[0]
                info["iso"] = f"ISO {iso}"

            dt = str(sub.get(36867) or exif.get(306) or "").strip()
            if dt:
                info["date"] = dt[:10].replace(":", "-")
    except Exception:
        return {}

    parts = [info[k] for k in ("camera", "focal", "aperture", "shutter", "iso") if k in info]
    if parts:
        info["summary"] = " · ".join(parts)
    return info


def apply_darkroom_print_finishing(
    pil_img: Image.Image,
    float_srgb: np.ndarray | None = None,
    easel_border: str = "none",
    dry_down_comp: float = 0.0,
    analog_meta: dict | None = None,
) -> tuple[Image.Image, np.ndarray | None]:
    """Apply paper dry-down compensation and archival darkroom easel borders at export time."""
    border_key = easel_border if easel_border in EASEL_BORDERS else "none"
    comp = float(np.clip(float(dry_down_comp or 0.0), 0.0, 0.15))

    if border_key == "none" and comp < 0.002:
        return pil_img, float_srgb

    arr_f = (
        np.clip(np.asarray(float_srgb, dtype=np.float32), 0.0, 1.0).copy()
        if float_srgb is not None
        else np.asarray(pil_img.convert("RGB"), dtype=np.float32) / 255.0
    )

    # Dry-down compensation: fiber-base darkroom prints dry ~5-12% darker; lift tone smoothly
    if comp >= 0.002:
        gamma = 1.0 / (1.0 + comp * 0.85)
        arr_f = np.power(np.clip(arr_f, 0.0, 1.0), gamma).astype(np.float32)

    pad_bottom = 0
    if border_key != "none":
        h, w = arr_f.shape[:2]
        short = min(h, w)
        if border_key in ("white_gallery", "gallery_caption"):
            side = max(20, int(round(short * 0.065)))
            pad_top, pad_left, pad_right = side, side, side
            pad_bottom = int(round(side * (1.65 if border_key == "gallery_caption" else 1.32)))
            bg_rgb = np.array([0.965, 0.960, 0.945], dtype=np.float32)
            keyline_rgb = np.array([0.16, 0.16, 0.16], dtype=np.float32)
        elif border_key == "black_rebate":
            pad = max(14, int(round(short * 0.032)))
            pad_top = pad_left = pad_right = pad_bottom = pad
            bg_rgb = np.array([0.035, 0.034, 0.033], dtype=np.float32)
            keyline_rgb = np.array([0.11, 0.11, 0.11], dtype=np.float32)
        else:
            # "white_thin"
            pad = max(12, int(round(short * 0.025)))
            pad_top = pad_left = pad_right = pad_bottom = pad
            bg_rgb = np.array([0.965, 0.960, 0.945], dtype=np.float32)
            keyline_rgb = None

        canvas = np.empty((h + pad_top + pad_bottom, w + pad_left + pad_right, 3), dtype=np.float32)
        canvas[:, :, :] = bg_rgb
        canvas[pad_top : pad_top + h, pad_left : pad_left + w, :] = arr_f
        if keyline_rgb is not None:
            t = max(1, short // 900)
            y0, y1 = max(0, pad_top - t), min(canvas.shape[0], pad_top + h + t)
            x0, x1 = max(0, pad_left - t), min(canvas.shape[1], pad_left + w + t)
            canvas[y0:pad_top, x0:x1] = keyline_rgb
            canvas[pad_top + h : y1, x0:x1] = keyline_rgb
            canvas[pad_top : pad_top + h, x0:pad_left] = keyline_rgb
            canvas[pad_top : pad_top + h, pad_left + w : x1] = keyline_rgb
        arr_f = canvas

    arr_f = np.clip(arr_f, 0.0, 1.0).astype(np.float32)
    out_pil = Image.fromarray(np.rint(arr_f * 255.0).astype(np.uint8))

    if border_key == "gallery_caption" and pad_bottom > 16:
        from PIL import ImageFont

        from .platform_io import load_ui_font

        caption_txt = format_analog_caption(analog_meta or {}) or "HALURO · LABORATORIO ANALÓGICO"
        draw = ImageDraw.Draw(out_pil)
        font_sz = max(11, int(round(pad_bottom * 0.24)))
        try:
            font = load_ui_font("mono", font_sz)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), caption_txt, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = max(10, (out_pil.width - tw) // 2)
        ty = out_pil.height - pad_bottom + max(4, (pad_bottom - th) // 2)
        draw.text((tx, ty), caption_txt, fill=(72, 70, 66), font=font)
        if float_srgb is not None:
            arr_f = np.asarray(out_pil.convert("RGB"), dtype=np.float32) / 255.0

    return out_pil, (arr_f if float_srgb is not None else None)


def apply_digital_negative_contact(pil_img: Image.Image, float_srgb: np.ndarray | None = None):
    """Convert a finished print into a horizontally flipped B&W contact negative with UV curve (Cap. 13)."""
    if float_srgb is not None:
        arr = np.clip(np.asarray(float_srgb, dtype=np.float32), 0.0, 1.0)
    else:
        arr = np.asarray(pil_img.convert("RGB"), dtype=np.float32) / 255.0

    y = np.sum(arr * LUMA, axis=-1, keepdims=True)
    # Invert positive -> negative and apply gentle UV contact-print compensation curve
    inv = np.clip(1.0 - y, 0.0, 1.0)
    uv_neg = np.power(inv, 0.88).astype(np.float32)
    # Flip horizontally (emulsion-down contact against cyanotype / Pt-Pd / salt paper)
    uv_neg = uv_neg[:, ::-1, :]
    neg_rgb = np.repeat(uv_neg, 3, axis=-1)
    neg_u8 = (np.clip(neg_rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(neg_u8, mode="RGB"), neg_rgb


def save_output_image(
    pil_img,
    target_path,
    source_path=None,
    quality=96,
    float_srgb: np.ndarray | None = None,
    analog_meta: dict | None = None,
    easel_border: str = "none",
    dry_down_comp: float = 0.0,
    export_max_dim: int | None = None,
    digital_negative: bool = False,
    upscale_factor: float = 1.0,
    upscale_mode: str = "ibp",
):
    """Save developed image in JPG (4:4:4 + EXIF), PNG, or 16-bit (48-bit RGB) archival TIFF.

    The file is written to a temporary sibling and then moved into place, so an
    interrupted export can never leave a truncated master behind.
    """
    if float(upscale_factor or 1.0) > 1.01 and str(upscale_mode or "ibp").lower() != "off":
        from .superres import compute_target_dimensions, upscale_float_rgb

        src_f = (
            np.clip(np.asarray(float_srgb, dtype=np.float32), 0.0, 1.0)
            if float_srgb is not None
            else (np.asarray(pil_img.convert("RGB"), dtype=np.float32) / 255.0)
        )
        out_w, out_h, _ = compute_target_dimensions(
            src_f.shape[1], src_f.shape[0], upscale_factor=float(upscale_factor)
        )
        if out_w > src_f.shape[1] or out_h > src_f.shape[0]:
            float_srgb = upscale_float_rgb(src_f, out_w, out_h, mode=str(upscale_mode or "ibp"))
            pil_img = Image.fromarray((np.clip(float_srgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), mode="RGB")

    if export_max_dim and int(export_max_dim) > 0 and max(pil_img.size) > int(export_max_dim):
        scale = float(export_max_dim) / float(max(pil_img.size))
        new_w = max(1, int(round(pil_img.width * scale)))
        new_h = max(1, int(round(pil_img.height * scale)))
        pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        if float_srgb is not None:
            zoom_y = new_h / float(float_srgb.shape[0])
            zoom_x = new_w / float(float_srgb.shape[1])
            float_srgb = np.clip(
                scipy.ndimage.zoom(float_srgb, (zoom_y, zoom_x, 1.0), order=1),
                0.0,
                1.0,
            ).astype(np.float32)

    pil_img, float_srgb = apply_darkroom_print_finishing(
        pil_img,
        float_srgb=float_srgb,
        easel_border=easel_border,
        dry_down_comp=dry_down_comp,
        analog_meta=analog_meta,
    )
    if digital_negative:
        pil_img, float_srgb = apply_digital_negative_contact(pil_img, float_srgb=float_srgb)
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    ext = target_path.suffix.lower()

    tmp_path = target_path.with_name(f".{target_path.name}.part")

    try:
        if ext in (".tif", ".tiff"):
            if float_srgb is not None:
                save_tiff_16bit_rgb(float_srgb, tmp_path, analog_meta=analog_meta)
            else:
                # Fallback when caller only passed 8-bit PIL Image (contact sheets, legacy call)
                arr_f = np.asarray(pil_img.convert("RGB"), dtype=np.float32) / 255.0
                save_tiff_16bit_rgb(arr_f, tmp_path, analog_meta=analog_meta)
            os.replace(tmp_path, target_path)
            return pil_img

        if ext == ".dng":
            if float_srgb is not None:
                save_linear_dng_16bit(float_srgb, tmp_path, analog_meta=analog_meta)
            else:
                arr_f = np.asarray(pil_img.convert("RGB"), dtype=np.float32) / 255.0
                save_linear_dng_16bit(arr_f, tmp_path, analog_meta=analog_meta)
            os.replace(tmp_path, target_path)
            return pil_img

        exif_bytes = build_export_exif_bytes(source_path=source_path, analog_meta=analog_meta)
        icc_bytes = _get_srgb_icc_bytes()

        if ext == ".png":
            save_kwargs = {"format": "PNG", "compress_level": 4, "icc_profile": icc_bytes}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            pil_img.save(tmp_path, **save_kwargs)
        elif ext == ".webp":
            save_kwargs = {"format": "WEBP", "quality": quality, "method": 4, "icc_profile": icc_bytes}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            pil_img.save(tmp_path, **save_kwargs)
        else:
            # High-grade JPEG with 4:4:4 chroma subsampling=0 & embedded sRGB ICC to preserve grain and display gamut
            save_kwargs = {
                "format": "JPEG",
                "quality": quality,
                "subsampling": 0,
                "optimize": True,
                "icc_profile": icc_bytes,
            }
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            pil_img.save(tmp_path, **save_kwargs)

        os.replace(tmp_path, target_path)
        return pil_img
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def apply_dust_spot_healing(pos: np.ndarray, dust_spots=None) -> np.ndarray:
    """Gentle annular surround healing for pinpoint dust/hairs without IR channels."""
    if not dust_spots:
        return pos
    out = np.asarray(pos, dtype=np.float32).copy()
    h, w = out.shape[:2]
    max_dim = max(h, w)
    if max_dim < 8:
        return out

    for spot in dust_spots:
        if isinstance(spot, dict):
            nx = float(spot.get("x", -1.0))
            ny = float(spot.get("y", -1.0))
            nr = float(spot.get("r", 0.008))
        elif isinstance(spot, (list, tuple)) and len(spot) >= 2:
            nx = float(spot[0])
            ny = float(spot[1])
            nr = float(spot[2]) if len(spot) >= 3 else 0.008
        else:
            continue

        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            continue
        rad = max(2, min(int(round(max(0.002, min(0.045, nr)) * max_dim)), max_dim // 6))
        cx = int(round(nx * (w - 1)))
        cy = int(round(ny * (h - 1)))
        patch_r = rad * 2 + 4

        y0, y1 = max(0, cy - patch_r), min(h, cy + patch_r + 1)
        x0, x1 = max(0, cx - patch_r), min(w, cx + patch_r + 1)
        patch = out[y0:y1, x0:x1]
        if patch.size == 0:
            continue

        yy, xx = np.ogrid[y0:y1, x0:x1]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2, dtype=np.float32)
        ring_mask = (dist >= rad * 1.15) & (dist <= rad * 2.25)
        inner_mask = dist <= rad
        if not np.any(ring_mask) or not np.any(inner_mask):
            continue

        ring_vals = patch[ring_mask]
        ring_med = np.median(ring_vals, axis=0)
        ry, rx = np.nonzero(ring_mask)
        design = np.column_stack(
            [
                np.ones_like(rx, dtype=np.float32),
                (rx - (cx - x0)).astype(np.float32),
                (ry - (cy - y0)).astype(np.float32),
            ]
        )
        try:
            coeffs, _, _, _ = np.linalg.lstsq(design, ring_vals, rcond=None)
            gy, gx = np.meshgrid(
                np.arange(y0, y1, dtype=np.float32) - cy,
                np.arange(x0, x1, dtype=np.float32) - cx,
                indexing="ij",
            )
            fill = coeffs[0] + gy[..., None] * coeffs[1] + gx[..., None] * coeffs[2]
            fill = 0.65 * fill + 0.35 * ring_med
        except np.linalg.LinAlgError:
            fill = np.broadcast_to(ring_med, patch.shape)

        fill = np.clip(fill, 0.0, 1.0)
        alpha = np.where(inner_mask, 0.5 * (1.0 + np.cos(np.pi * np.clip(dist / max(rad, 1e-4), 0.0, 1.0))), 0.0)
        alpha = alpha[..., None].astype(np.float32)
        out[y0:y1, x0:x1] = patch * (1.0 - alpha) + fill * alpha

    return np.clip(out, 0.0, 1.0)


def apply_digital_denoise(
    lin: np.ndarray,
    luma_strength: float = 0.0,
    chroma_strength: float = 0.0,
) -> np.ndarray:
    """Edge-preserving digital noise reduction in linear space prior to film grain synthesis."""
    l_str = float(max(0.0, min(1.0, luma_strength)))
    c_str = float(max(0.0, min(1.0, chroma_strength)))
    if l_str <= 0.005 and c_str <= 0.005:
        return lin

    arr = np.maximum(np.asarray(lin, dtype=np.float32), 0.0)
    y = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    cb = arr[..., 2] - y
    cr = arr[..., 0] - y

    if c_str > 0.005:
        sigma_c = 1.0 + 3.2 * c_str
        cb_smooth = scipy.ndimage.gaussian_filter(cb, sigma=sigma_c)
        cr_smooth = scipy.ndimage.gaussian_filter(cr, sigma=sigma_c)
        cb = cb * (1.0 - c_str) + cb_smooth * c_str
        cr = cr * (1.0 - c_str) + cr_smooth * c_str

    if l_str > 0.005:
        sigma_l = 0.7 + 1.4 * l_str
        y_smooth = scipy.ndimage.gaussian_filter(y, sigma=sigma_l)
        # Edge protection: preserve high-frequency structural edges
        gy, gx = np.gradient(y)
        edge_mag = np.sqrt(gx * gx + gy * gy)
        edge_thresh = np.maximum(0.015, 0.08 * np.percentile(edge_mag, 90) + 1e-5)
        edge_protect = np.clip(edge_mag / edge_thresh, 0.0, 1.0)
        blend = l_str * (1.0 - 0.85 * edge_protect)
        y = y * (1.0 - blend) + y_smooth * blend

    r = np.maximum(0.0, y + cr)
    b = np.maximum(0.0, y + cb)
    g = np.maximum(0.0, (y - 0.2126 * r - 0.0722 * b) / 0.7152)
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def apply_defringe(lin: np.ndarray, strength: float = 0.0) -> np.ndarray:
    """Suppress purple/magenta and green lateral chromatic aberration along high-contrast edges."""
    amt = float(max(0.0, min(1.0, strength)))
    if amt <= 0.005:
        return lin

    arr = np.maximum(np.asarray(lin, dtype=np.float32), 0.0)
    y = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    local_max = scipy.ndimage.maximum_filter(y, size=5)
    local_min = scipy.ndimage.minimum_filter(y, size=5)
    edge_band = np.clip((local_max - local_min) * 3.5, 0.0, 1.0)

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Purple fringe: R & B elevated relative to G; Green fringe: G elevated relative to R & B
    purple_excess = np.maximum(0.0, np.minimum(r, b) - g)
    green_excess = np.maximum(0.0, g - np.maximum(r, b))
    p_w = np.clip(purple_excess * 4.0, 0.0, 1.0) * edge_band * amt
    g_w = np.clip(green_excess * 4.0, 0.0, 1.0) * edge_band * amt

    r_out = r - p_w * np.maximum(0.0, r - g)
    b_out = b - p_w * np.maximum(0.0, b - g)
    rb_avg = 0.5 * (r_out + b_out)
    g_out = g - g_w * np.maximum(0.0, g - rb_avg)
    return np.maximum(np.stack([r_out, g_out, b_out], axis=-1), 0.0).astype(np.float32)


def apply_local_dodge_burn(lin: np.ndarray, local_masks=None) -> np.ndarray:
    """Apply non-destructive linear-gradient and radial Dodge & Burn masks in linear exposure space."""
    if not local_masks:
        return lin
    h, w = lin.shape[:2]
    if h < 4 or w < 4:
        return lin

    yy, xx = np.meshgrid(
        np.linspace(0.0, 1.0, h, dtype=np.float32),
        np.linspace(0.0, 1.0, w, dtype=np.float32),
        indexing="ij",
    )
    total_ev_map = np.zeros((h, w), dtype=np.float32)
    total_farmer_map = np.zeros((h, w), dtype=np.float32)

    for mask in local_masks[:8]:
        if not isinstance(mask, dict):
            continue
        mtype = str(mask.get("type", "linear") or "linear").lower()
        mode = str(mask.get("mode", "exposure") or "exposure").lower()
        ev = float(max(-2.5, min(2.5, float(mask.get("ev", 0.0) or 0.0))))
        if abs(ev) < 1e-4:
            continue
        x1 = float(mask.get("x1", 0.5))
        y1 = float(mask.get("y1", 0.25))
        x2 = float(mask.get("x2", 0.5))
        y2 = float(mask.get("y2", 0.75))
        feather = float(max(0.05, min(1.0, float(mask.get("feather", 0.4) or 0.4))))
        invert = bool(mask.get("invert", False))

        if mtype == "radial":
            rx = max(0.03, abs(x2 - x1))
            ry = max(0.03, abs(y2 - y1))
            dist = np.sqrt(((xx - x1) / rx) ** 2 + ((yy - y1) / ry) ** 2)
            inner = max(0.0, 1.0 - feather)
            t = np.clip((dist - inner) / max(1e-4, 1.0 - inner), 0.0, 1.0)
            alpha = 1.0 - (t * t * (3.0 - 2.0 * t))
        else:
            dx = x2 - x1
            dy = y2 - y1
            len_sq = dx * dx + dy * dy
            if len_sq < 1e-6:
                continue
            proj = ((xx - x1) * dx + (yy - y1) * dy) / len_sq
            half_span = max(0.02, 0.5 * feather)
            t = np.clip((proj - (0.5 - half_span)) / (2.0 * half_span), 0.0, 1.0)
            alpha = 1.0 - (t * t * (3.0 - 2.0 * t))

        if invert:
            alpha = 1.0 - alpha
        if mode == "farmer":
            # Farmer's Reducer local bleach: brightens highlights faster than shadows
            total_farmer_map += max(0.0, abs(ev) / 2.0) * alpha
        else:
            total_ev_map += ev * alpha

    out = lin
    if np.any(np.abs(total_ev_map) > 1e-4):
        gain = np.power(2.0, np.clip(total_ev_map, -3.5, 3.5)).astype(np.float32)
        out = np.maximum(out * gain[..., None], 0.0)
    if np.any(total_farmer_map > 1e-4):
        f_amt = np.clip(total_farmer_map, 0.0, 1.25)[..., None]
        luma = np.maximum(np.sum(out * LUMA, axis=-1, keepdims=True), 1e-5)
        # Proportional silver subtraction: lifts upper midtones/highlights while anchoring Zone I-II
        hi_weight = np.clip((luma - 0.03) / 0.35, 0.0, 1.0) ** 0.75
        bleach_gain = 1.0 + f_amt * (0.95 * hi_weight)
        out = np.maximum(out * bleach_gain, 0.0)
    return out


def apply_optical_sharpen(srgb_arr: np.ndarray, mode: str = "off", amount: float = 1.0) -> np.ndarray:
    """Luminance-only edge-protected optical sharpening that restores lens/scanner acutance without harsh grain."""
    if not mode or mode == "off" or amount <= 0.01:
        return srgb_arr

    amt = float(np.clip(amount, 0.0, 2.5))
    arr = np.clip(np.asarray(srgb_arr, dtype=np.float32), 0.0, 1.0)
    y = np.sum(arr * LUMA, axis=-1)

    if mode == "scanner":
        # Flatbed / glass-bed deconvolution: medium-radius optical recovery + fine pass
        blur_fine = scipy.ndimage.gaussian_filter(y, sigma=0.95)
        blur_med = scipy.ndimage.gaussian_filter(y, sigma=1.85)
        detail = 0.60 * (y - blur_fine) + 0.40 * (y - blur_med)
        cor_thresh = 0.016
        strength = 0.92 * amt
    else:
        # "lab" (Minilab Frontier / Noritsu optical micro-acutance)
        blur_fine = scipy.ndimage.gaussian_filter(y, sigma=0.80)
        detail = y - blur_fine
        cor_thresh = 0.013
        strength = 0.78 * amt

    # Grain-protection coring gate: ignores low-amplitude silver grain in skies/smooth skin
    edge_gate = np.clip((np.abs(detail) - cor_thresh) / (cor_thresh * 2.2), 0.0, 1.0)
    # Tonal protection: avoid harsh specular halos at 0.0 and 1.0
    tonal_guard = 0.35 + 0.65 * (4.0 * y * np.maximum(0.0, 1.0 - y))

    delta_y = detail * edge_gate * tonal_guard * strength
    y_sharp = np.clip(y + delta_y, 0.0, 1.0)

    # Apply strictly to luminance preserving exact chromaticity
    ratio = (y_sharp + 1e-4) / (y + 1e-4)
    out = arr * ratio[..., None]
    return np.clip(out, 0.0, 1.0)


def apply_vignette(lin, strength=1.0):
    """Simulates authentic analog optical lens falloff with smoothstep radial feathering."""
    if strength <= 0.001:
        return lin
    h, w = lin.shape[:2]
    y = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    r = np.sqrt(x * x + y * y) / np.sqrt(2.0)
    falloff = np.clip((r - 0.25) / 0.75, 0.0, 1.0)
    falloff_smooth = falloff * falloff * (3.0 - 2.0 * falloff)
    max_attenuation = np.clip(0.55 * strength, 0.0, 0.85)
    vig = (1.0 - max_attenuation * falloff_smooth)[..., None]
    return lin * vig


def apply_halation(lin, strength=1.0, threshold=0.70, tint=(1.0, 0.28, 0.06)):
    """Simulates red halation around high-contrast specular highlights."""
    if strength <= 0.01:
        return lin

    luma = np.sum(lin * LUMA, axis=-1)
    # Use a softer highlight knee so normal bright highlights (not only clipped
    # >0.80 linear peaks) respond clearly when the user increases halation.
    eff_thr = max(0.35, float(threshold) - 0.18)
    over = np.maximum(0.0, luma - eff_thr)

    # Combine a tight inner rim with a wider 0.8% frame-width bloom
    sigma_wide = max(2.0, lin.shape[1] * 0.008)
    sigma_inner = max(1.0, sigma_wide * 0.35)
    glow_wide = scipy.ndimage.gaussian_filter(over, sigma=sigma_wide)
    glow_inner = scipy.ndimage.gaussian_filter(over, sigma=sigma_inner)
    glow = 0.65 * glow_wide + 0.35 * glow_inner

    tint_arr = np.array(tint, dtype=np.float32)[None, None, :]
    glow_rgb = glow[..., None] * tint_arr * (strength * 0.55)
    return lin + glow_rgb


def apply_grain(rgb, amount=0.02, size=1.0, seed=None, chroma=0.0, ref_dim=1280, highlight_mask=0.0):
    """Add multi-octave organic silver-halide / dye-cloud film grain.

    Uses a local deterministic RNG seeded per frame so preview and export carry
    the same grain structure. Combines three spatial octaves (microcrystal,
    medium silver clump, and soft macro-clump) with bicubic resampling to avoid
    rectangular grid artifacts, an asymmetric film tonal envelope (stronger in
    shadows-to-midtones than dense highlights), and optional subtle chromatic
    dye-cloud variation for color stocks.
    """
    if amount <= 0.001:
        return rgb

    rng = np.random.default_rng(seed)
    h, w = rgb.shape[:2]
    res_scale = max(1.0, max(h, w) / float(ref_dim)) if ref_dim else 1.0
    base_size = max(0.85, float(size)) * res_scale

    # Octave 1: fine microcrystal texture (slightly softer at high res_scale)
    if res_scale > 1.35:
        nfh, nfw = max(1, int(h / (0.85 * res_scale))), max(1, int(w / (0.85 * res_scale)))
        fine_small = rng.normal(0.0, 1.0, (nfh, nfw)).astype(np.float32)
        fine = np.asarray(
            Image.fromarray(fine_small).resize((w, h), Image.Resampling.BICUBIC),
            dtype=np.float32,
        )
    else:
        fine = rng.normal(0.0, 1.0, (h, w)).astype(np.float32)

    # Octave 2: medium silver-halide / dye clump
    med_step = max(1.35, base_size * 1.45)
    nmh, nmw = max(1, int(h / med_step)), max(1, int(w / med_step))
    med_small = rng.normal(0.0, 1.0, (nmh, nmw)).astype(np.float32)
    med = np.asarray(
        Image.fromarray(med_small).resize((w, h), Image.Resampling.BICUBIC),
        dtype=np.float32,
    )

    # Octave 3: soft organic macro-clump
    mac_step = max(2.6, base_size * 2.85)
    nch, ncw = max(1, int(h / mac_step)), max(1, int(w / mac_step))
    mac_small = rng.normal(0.0, 1.0, (nch, ncw)).astype(np.float32)
    mac = np.asarray(
        Image.fromarray(mac_small).resize((w, h), Image.Resampling.BICUBIC),
        dtype=np.float32,
    )

    luma_noise = 0.24 * fine + 0.54 * med + 0.22 * mac
    std = float(np.std(luma_noise))
    if std > 1e-6:
        luma_noise = luma_noise / std

    chroma_ratio = float(np.clip(chroma, 0.0, 0.6))
    if chroma_ratio > 1e-3 and rgb.ndim == 3 and rgb.shape[2] == 3:
        c_step = max(1.6, base_size * 1.6)
        ch, cw = max(1, int(h / c_step)), max(1, int(w / c_step))
        c_small = rng.normal(0.0, 1.0, (ch, cw, 3)).astype(np.float32)
        c_channels = [
            np.asarray(
                Image.fromarray(c_small[..., idx]).resize((w, h), Image.Resampling.BICUBIC),
                dtype=np.float32,
            )
            for idx in range(3)
        ]
        chroma_noise = np.stack(c_channels, axis=-1)
        chroma_noise -= np.mean(chroma_noise, axis=-1, keepdims=True)
        chroma_noise *= np.array([1.10, 0.75, 1.15], dtype=np.float32)[None, None, :]
        c_std = float(np.std(chroma_noise))
        if c_std > 1e-6:
            chroma_noise = chroma_noise / c_std
        noise_rgb = luma_noise[..., None] * (1.0 - chroma_ratio) + chroma_noise * chroma_ratio
    else:
        noise_rgb = luma_noise[..., None]

    luma = np.sum(rgb * LUMA, axis=-1, keepdims=True)
    mid_peak = 4.0 * luma * np.maximum(0.0, 1.0 - luma)
    shadow_bias = np.clip(1.15 - 0.55 * luma, 0.35, 1.15)
    weight = (0.28 + 0.72 * mid_peak) * shadow_bias
    if float(highlight_mask or 0.0) > 0.005:
        # Pyro proportional stain masks grain density in upper midtones & highlights
        hi_fade = np.clip((luma - 0.42) / 0.50, 0.0, 1.0)
        weight = weight * (1.0 - float(np.clip(highlight_mask, 0.0, 0.85)) * hi_fade)

    noisy_rgb = rgb + noise_rgb * (amount * weight)
    return np.clip(noisy_rgb, 0.0, 1.0)


def draw_date_stamp(image, date_str=None):
    """Draws a classic vintage orange/amber 7-segment style date stamp."""
    if not date_str:
        import datetime
        date_str = datetime.datetime.now().strftime("'%y %m %d")

    draw = ImageDraw.Draw(image)
    w, h = image.size
    font_size = max(16, int(h * 0.032))
    font = load_ui_font("mono-bold", font_size)

    bbox = draw.textbbox((0, 0), date_str, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = w - tw - int(w * 0.04)
    y = h - th - int(h * 0.04)

    # Outer glow + main stamp
    glow_color = (180, 50, 0, 120)
    text_color = (255, 140, 20, 240)
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)]:
        draw.text((x + dx, y + dy), date_str, font=font, fill=glow_color)
    draw.text((x, y), date_str, font=font, fill=text_color)
    return image


def _stable_grain_seed(image_input, film_key) -> int:
    """Derive a deterministic grain seed from the source identity and the film stock.

    The seed must depend only on *what* is being developed, never on *when*:
    that is what guarantees that the interactive preview and the exported master
    carry the exact same grain pattern, and that two exports of the same roll
    are byte-identical.
    """
    if isinstance(image_input, (str, Path)):
        identity = f"{Path(image_input).name}|{film_key}"
    else:
        identity = f"inline|{film_key}"
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


DEV_PROCESSES = {
    "standard": {
        "name": "Estándar (C-41 / D-76)",
        "ev_offset": 0.0,
        "contrast_mult": 1.0,
        "grain_mult": 1.0,
        "clump_mult": 1.0,
        "acutance": 0.0,
        "compensating": 0.0,
        "pyro_mask": 0.0,
        "shadow_lift": 0.0,
    },
    "d76_1_1": {
        "name": "Kodak D-76 (1:1 · clásico equilibrado)",
        "ev_offset": 0.0,
        "contrast_mult": 1.02,
        "grain_mult": 0.96,
        "clump_mult": 0.98,
        "acutance": 0.18,
        "compensating": 0.15,
        "pyro_mask": 0.0,
        "shadow_lift": 0.02,
    },
    "d23_divided": {
        "name": "Kodak D-23 Dividido (Ansel Adams · baño de agua)",
        "ev_offset": 0.05,
        "contrast_mult": 0.95,
        "grain_mult": 0.88,
        "clump_mult": 0.92,
        "acutance": 0.12,
        "compensating": 0.72,
        "pyro_mask": 0.0,
        "shadow_lift": 0.08,
    },
    "pmk_pyro": {
        "name": "PMK Pyro (Hutchings · mancha y acutancia)",
        "ev_offset": 0.0,
        "contrast_mult": 1.04,
        "grain_mult": 0.92,
        "clump_mult": 0.95,
        "acutance": 0.55,
        "compensating": 0.58,
        "pyro_mask": 0.65,
        "shadow_lift": 0.03,
    },
    "pyrocat_hd": {
        "name": "Pyrocat-HD (Sandy King · catecol alta definición)",
        "ev_offset": 0.0,
        "contrast_mult": 1.06,
        "grain_mult": 0.82,
        "clump_mult": 0.88,
        "acutance": 0.52,
        "compensating": 0.45,
        "pyro_mask": 0.50,
        "shadow_lift": 0.02,
    },
    "rodinal_1_50": {
        "name": "Rodinal 1:50 (alta acutancia y grano cincelado)",
        "ev_offset": 0.0,
        "contrast_mult": 1.05,
        "grain_mult": 1.24,
        "clump_mult": 1.18,
        "acutance": 0.62,
        "compensating": 0.25,
        "pyro_mask": 0.0,
        "shadow_lift": 0.0,
    },
    "windisch_comp": {
        "name": "Windisch / POTA (compensador extremo 10+ pasos)",
        "ev_offset": 0.05,
        "contrast_mult": 0.90,
        "grain_mult": 0.92,
        "clump_mult": 0.95,
        "acutance": 0.30,
        "compensating": 1.45,
        "pyro_mask": 0.0,
        "shadow_lift": 0.10,
    },
    "stand_rodinal": {
        "name": "Stand / Rodinal 1+100 (alta acutancia)",
        "ev_offset": 0.0,
        "contrast_mult": 0.96,
        "grain_mult": 1.15,
        "clump_mult": 1.10,
        "acutance": 0.45,
        "compensating": 1.0,
        "pyro_mask": 0.0,
        "shadow_lift": 0.04,
    },
    "push_1": {
        "name": "Push +1 EV (forzado 1 paso)",
        "ev_offset": 0.35,
        "contrast_mult": 1.12,
        "grain_mult": 1.20,
        "clump_mult": 1.15,
        "acutance": 0.15,
        "compensating": 0.0,
        "pyro_mask": 0.0,
        "shadow_lift": 0.0,
    },
    "push_2": {
        "name": "Push +2 EV (forzado 2 pasos)",
        "ev_offset": 0.70,
        "contrast_mult": 1.24,
        "grain_mult": 1.40,
        "clump_mult": 1.32,
        "acutance": 0.25,
        "compensating": 0.0,
        "pyro_mask": 0.0,
        "shadow_lift": 0.0,
    },
    "pull_1": {
        "name": "Pull -1 EV (subrevelado suave)",
        "ev_offset": -0.25,
        "contrast_mult": 0.88,
        "grain_mult": 0.85,
        "clump_mult": 0.90,
        "acutance": 0.0,
        "compensating": 0.35,
        "pyro_mask": 0.0,
        "shadow_lift": 0.0,
    },
}


# Enlarger head optical physics (Darkroom Cookbook Cap. 4 p. 33 & Cap. 8 p. 86)
ENLARGER_HEADS: dict[str, dict[str, float | str]] = {
    "standard": {"name": "Estándar (Neutro)", "contrast": 1.0, "acutance": 0.0, "grain_mult": 1.0, "mid_lift": 0.0},
    "condenser": {
        "name": "Condensador (Efecto Callier · microcontraste)",
        "contrast": 1.09,
        "acutance": 0.28,
        "grain_mult": 1.14,
        "mid_lift": -0.015,
    },
    "diffuser": {
        "name": "Difusor / Luz Fría (Cold Light · suave)",
        "contrast": 0.94,
        "acutance": 0.0,
        "grain_mult": 0.84,
        "mid_lift": 0.022,
    },
}
VALID_ENLARGER_HEADS = tuple(ENLARGER_HEADS.keys())

# Paper developer silver image tone (separate from paper base tint — Darkroom Cookbook Cap. 8 p. 78)
PAPER_DEVELOPERS: dict[str, dict] = {
    "neutral": {
        "name": "Neutro (Estándar)",
        "contrast": 1.0,
        "mid_lift": 0.0,
        "dmax_shift": 0.0,
        "tint": (0.0, 0.0, 0.0),
    },
    "amidol": {
        "name": "Amidol (Edward Weston · negros profundos fríos)",
        "contrast": 1.08,
        "mid_lift": -0.01,
        "dmax_shift": -0.018,
        "tint": (-0.012, -0.004, 0.016),
    },
    "ansco130": {
        "name": "Ansco 130 (Ansel Adams · escala larga luminosa)",
        "contrast": 1.03,
        "mid_lift": 0.024,
        "dmax_shift": -0.012,
        "tint": (-0.004, 0.0, 0.005),
    },
    "dektol": {
        "name": "Kodak Dektol / D-72 (exposición neutro-frío)",
        "contrast": 1.06,
        "mid_lift": 0.0,
        "dmax_shift": -0.010,
        "tint": (-0.008, -0.002, 0.010),
    },
    "selectol": {
        "name": "Selectol-Soft / D-52 (cálido suave en luces)",
        "contrast": 0.92,
        "mid_lift": 0.018,
        "dmax_shift": 0.006,
        "tint": (0.024, 0.010, -0.026),
    },
}
VALID_PAPER_DEVELOPERS = tuple(PAPER_DEVELOPERS.keys())

# Paper base support tint (applied proportionally to highlight reflectance)
PAPER_BASES: dict[str, dict] = {
    "none": {"name": "Sin tinte de base", "rgb": (1.0, 1.0, 1.0), "dmax_floor": 0.0},
    "fb_bright": {"name": "Baritado Blanco Brillante", "rgb": (0.985, 0.992, 1.0), "dmax_floor": 0.0},
    "fb_ivory": {"name": "Baritado Marfil Cálido", "rgb": (1.0, 0.968, 0.905), "dmax_floor": 0.006},
    "cotton_matte": {"name": "Algodón Mate Museo", "rgb": (0.985, 0.962, 0.918), "dmax_floor": 0.026},
}
VALID_PAPER_BASES = tuple(PAPER_BASES.keys())

# Tim Rudman sequential dual-toning baths (Cap. 10 pp. 118-119)
# Shadow toners act bottom-up (Zones I-IV); Highlight toners act top-down (Zones V-IX).
DUAL_SHADOW_TONERS: dict[str, dict] = {
    "none": {"name": "Sin virado de sombras", "tint": (0.0, 0.0, 0.0), "dmax_boost": 0.0},
    "selenium": {"name": "Selenio 1:19 (berenjena frío + D-max)", "tint": (0.055, -0.024, 0.036), "dmax_boost": 0.022},
    "split_selenium": {"name": "Selenio 1:9 (ciruela profundo)", "tint": (0.088, -0.038, 0.052), "dmax_boost": 0.032},
    "platinum": {"name": "Platino / Paladio (pizarra fría)", "tint": (-0.018, -0.005, 0.032), "dmax_boost": 0.012},
    "iron_blue": {"name": "Azul de Hierro / Prusia", "tint": (-0.075, -0.012, 0.095), "dmax_boost": 0.015},
}
VALID_DUAL_SHADOW_TONERS = tuple(DUAL_SHADOW_TONERS.keys())

DUAL_HIGHLIGHT_TONERS: dict[str, dict] = {
    "none": {"name": "Sin virado de luces", "tint": (0.0, 0.0, 0.0)},
    "sepia": {"name": "Sepia Sulfuro (cálido clásico)", "tint": (0.105, 0.042, -0.115)},
    "gold_gp1": {"name": "Oro GP-1 (azul pizarra protector)", "tint": (-0.052, -0.010, 0.078)},
    "copper": {"name": "Cobre (rojizo cálido)", "tint": (0.118, 0.014, -0.082)},
    "tea": {"name": "Té / Pergamino antiguo", "tint": (0.072, 0.044, -0.068)},
}
VALID_DUAL_HIGHLIGHT_TONERS = tuple(DUAL_HIGHLIGHT_TONERS.keys())


def apply_enlarger_head(display: np.ndarray, head: str = "standard") -> np.ndarray:
    """Apply Condenser (Callier effect) or Diffuser (Cold Light) optical transfer."""
    key = str(head or "standard").strip().lower()
    if key not in ENLARGER_HEADS or key == "standard":
        return display
    spec = ENLARGER_HEADS[key]
    out = np.clip(display.astype(np.float32, copy=False), 0.0, 1.0)
    contrast = float(spec["contrast"])
    mid_lift = float(spec["mid_lift"])
    if abs(contrast - 1.0) > 0.005:
        out = np.clip(0.48 + (out - 0.48) * contrast, 0.0, 1.0)
    if abs(mid_lift) > 0.001:
        y = np.sum(out * LUMA, axis=-1, keepdims=True)
        mid_bell = 4.0 * y * np.maximum(0.0, 1.0 - y)
        out = np.clip(out + mid_lift * mid_bell, 0.0, 1.0)
    if float(spec["acutance"]) > 0.01:
        out = apply_optical_sharpen(out, mode="lab", amount=float(spec["acutance"]))
    return out


def apply_bw_darkroom_print(
    display: np.ndarray,
    paper_dev: str = "neutral",
    paper_base: str = "none",
    bw_grade00: float = 0.0,
    bw_grade5: float = 0.0,
    bw_preflash: float = 0.0,
) -> np.ndarray:
    """Apply B&W darkroom print controls: Split-Grade 00/5, Pre-flash, Paper Developer & Paper Base."""
    p_dev = str(paper_dev or "neutral").strip().lower()
    p_base = str(paper_base or "none").strip().lower()
    g00 = float(np.clip(bw_grade00 or 0.0, -1.0, 1.0))
    g5 = float(np.clip(bw_grade5 or 0.0, -1.0, 1.0))
    preflash = float(np.clip(bw_preflash or 0.0, 0.0, 1.0))

    if (
        p_dev == "neutral"
        and p_base == "none"
        and abs(g00) < 0.005
        and abs(g5) < 0.005
        and preflash < 0.005
    ):
        return display

    out = np.clip(display.astype(np.float32, copy=False), 0.0, 1.0)
    y = np.sum(out * LUMA, axis=-1, keepdims=True)

    # 1. Pre-flashing (Les McLean): overcomes paper inertia in Zone VIII-X without lifting shadows
    if preflash > 0.005:
        hi_mask = np.power(np.clip((y - 0.58) / 0.42, 0.0, 1.0), 1.5)
        out = np.clip(out - (0.075 * preflash) * hi_mask, 0.0, 1.0)
        y = np.sum(out * LUMA, axis=-1, keepdims=True)

    # 2. Split-Grade 00 (soft highlight/midtone burn) & Grade 5 (hard shadow contrast)
    if abs(g00) > 0.005:
        hi_w = np.clip((y - 0.30) / 0.70, 0.0, 1.0)
        out = np.clip(out - 0.14 * g00 * hi_w * (1.0 - 0.35 * y), 0.0, 1.0)
    if abs(g5) > 0.005:
        lo_w = np.clip((0.55 - y) / 0.55, 0.0, 1.0)
        out = np.clip(out - 0.16 * g5 * lo_w * y * 2.0, 0.0, 1.0)

    # 3. Paper Developer (silver image tone + tonal curve)
    if p_dev in PAPER_DEVELOPERS and p_dev != "neutral":
        dev_spec = PAPER_DEVELOPERS[p_dev]
        y = np.sum(out * LUMA, axis=-1, keepdims=True)
        out = np.clip(0.48 + (out - 0.48) * float(dev_spec["contrast"]), 0.0, 1.0)
        mid_bell = 4.0 * y * np.maximum(0.0, 1.0 - y)
        if abs(float(dev_spec["mid_lift"])) > 0.001:
            out = np.clip(out + float(dev_spec["mid_lift"]) * mid_bell, 0.0, 1.0)
        if abs(float(dev_spec["dmax_shift"])) > 0.001:
            sh_w = np.clip((0.35 - y) / 0.35, 0.0, 1.0) ** 1.4
            out = np.clip(out + float(dev_spec["dmax_shift"]) * sh_w, 0.0, 1.0)
        tint = np.array(dev_spec["tint"], dtype=np.float32)[None, None, :]
        # Silver image tone acts strongest in shadows & midtones (where silver density lives)
        silver_w = np.clip(4.0 * y * np.maximum(0.0, 1.0 - y) + 0.35 * (1.0 - y), 0.0, 1.0)
        out = np.clip(out + tint * silver_w, 0.0, 1.0)

    # 4. Paper Base tint & matte D-max floor (acts on paper reflectance)
    if p_base in PAPER_BASES and p_base != "none":
        base_spec = PAPER_BASES[p_base]
        dmax_floor = float(base_spec["dmax_floor"])
        if dmax_floor > 0.001:
            out = dmax_floor + out * (1.0 - dmax_floor)
        base_rgb = np.array(base_spec["rgb"], dtype=np.float32)[None, None, :]
        y = np.sum(out * LUMA, axis=-1, keepdims=True)
        paper_w = np.power(np.clip(y, 0.0, 1.0), 1.15)
        out = np.clip(out * (1.0 - paper_w) + (out * base_rgb) * paper_w, 0.0, 1.0)

    return out


def apply_dual_toning(
    display: np.ndarray,
    toner_shadows: str = "none",
    toner_shadows_amt: float = 0.0,
    toner_highlights: str = "none",
    toner_highlights_amt: float = 0.0,
) -> np.ndarray:
    """Apply Tim Rudman sequential chemical dual-toning (bottom-up shadow + top-down highlight)."""
    sh_key = str(toner_shadows or "none").strip().lower()
    hi_key = str(toner_highlights or "none").strip().lower()
    sh_amt = float(np.clip(toner_shadows_amt or 0.0, 0.0, 1.0))
    hi_amt = float(np.clip(toner_highlights_amt or 0.0, 0.0, 1.0))

    has_sh = sh_key in DUAL_SHADOW_TONERS and sh_key != "none" and sh_amt > 0.005
    has_hi = hi_key in DUAL_HIGHLIGHT_TONERS and hi_key != "none" and hi_amt > 0.005
    if not has_sh and not has_hi:
        return display

    out = np.clip(display.astype(np.float32, copy=False), 0.0, 1.0)
    y = np.sum(out * LUMA, axis=-1, keepdims=True)

    # Step 1: Shadow bath (bottom-up: Zones I-IV, fading smoothly above Zone VI)
    if has_sh:
        spec = DUAL_SHADOW_TONERS[sh_key]
        t_lo = np.clip((y - 0.015) / 0.16, 0.0, 1.0)
        t_hi = 1.0 - np.clip((y - 0.34) / 0.44, 0.0, 1.0)
        sh_mask = (t_lo * t_lo * (3.0 - 2.0 * t_lo)) * (t_hi * t_hi * (3.0 - 2.0 * t_hi))
        tint = np.array(spec["tint"], dtype=np.float32)[None, None, :]
        out = np.clip(out + tint * (sh_mask * sh_amt), 0.0, 1.0)
        dmax_boost = float(spec["dmax_boost"])
        if dmax_boost > 0.001:
            deep_w = np.clip((0.28 - y) / 0.28, 0.0, 1.0) ** 1.3
            out = np.clip(out - (dmax_boost * sh_amt) * deep_w, 0.0, 1.0)

    # Step 2: Highlight bath (top-down: Zones V-IX, leaving deep shadows intact)
    if has_hi:
        spec = DUAL_HIGHLIGHT_TONERS[hi_key]
        t_up = np.clip((y - 0.28) / 0.40, 0.0, 1.0)
        t_top = 1.0 - np.clip((y - 0.90) / 0.10, 0.0, 1.0)
        hi_mask = (t_up * t_up * (3.0 - 2.0 * t_up)) * (0.25 + 0.75 * (t_top * t_top * (3.0 - 2.0 * t_top)))
        tint = np.array(spec["tint"], dtype=np.float32)[None, None, :]
        out = np.clip(out + tint * (hi_mask * hi_amt), 0.0, 1.0)

    return out


def apply_farmer_bleach(display: np.ndarray, amount: float = 0.0) -> np.ndarray:
    """Apply Jay Dusard global Farmer's Reducer bleaching: brightens highlights & boosts microcontrast."""
    amt = float(np.clip(amount or 0.0, 0.0, 1.0))
    if amt < 0.005:
        return display
    out = np.clip(display.astype(np.float32, copy=False), 0.0, 1.0)
    y = np.sum(out * LUMA, axis=-1, keepdims=True)
    # Subtracting constant silver lifts Zone VI-IX much faster than Zone I-II
    hi_lift = np.power(np.clip((y - 0.18) / 0.82, 0.0, 1.0), 1.35) * (1.0 - 0.55 * np.clip((y - 0.88) / 0.12, 0.0, 1.0))
    out = np.clip(out + (0.16 * amt) * hi_lift, 0.0, 1.0)
    # Subtle microcontrast sparkle in upper midtones
    if amt > 0.05:
        out = apply_optical_sharpen(out, mode="lab", amount=0.22 * amt)
    return out


BW_OPTICAL_FILTERS: dict[str, tuple[float, float, float]] = {
    "yellow": (0.44, 0.50, 0.06),  # #8 Amarillo (contraste suave de cielos)
    "orange": (0.62, 0.35, 0.03),  # #21 Naranja (cielos marcados, piel limpia)
    "red": (0.80, 0.19, 0.01),     # #25 Rojo (dramático, cielos oscuros)
    "green": (0.20, 0.72, 0.08),   # #11 Verde (follaje y retrato natural)
    "blue": (0.10, 0.25, 0.65),    # #47 Azul (atmósfera y neblina)
}
VALID_BW_FILTERS = ("none", *BW_OPTICAL_FILTERS.keys())

# Ansel Adams Zone System development contraction/expansion (N-2 .. N+2).
# "Expose for the shadows, develop for the highlights":
# Pivots above Zone III (linear ~0.045) so shadow detail stays anchored while
# midtones and highlights contract (N-2, N-1) or expand (N+1, N+2).
ZONE_DEV_PROFILES: dict[str, dict[str, float | str]] = {
    "N-2": {"name": "N−2 (Contracción fuerte)", "gamma": 0.78, "shoulder": 0.38},
    "N-1": {"name": "N−1 (Contracción suave)", "gamma": 0.89, "shoulder": 0.18},
    "N": {"name": "N (Revelado normal)", "gamma": 1.00, "shoulder": 0.00},
    "N+1": {"name": "N+1 (Expansión suave)", "gamma": 1.13, "shoulder": 0.00},
    "N+2": {"name": "N+2 (Expansión fuerte)", "gamma": 1.28, "shoulder": 0.08},
}
VALID_ZONE_DEVS = tuple(ZONE_DEV_PROFILES.keys())


def apply_zone_system_dev(lin: np.ndarray, zone_dev: str = "N") -> np.ndarray:
    """Apply Zone System N-2..N+2 development around Zone III anchor in linear light."""
    key = str(zone_dev or "N").strip().upper()
    if key not in ZONE_DEV_PROFILES or key == "N":
        return lin
    spec = ZONE_DEV_PROFILES[key]
    gamma = float(spec["gamma"])
    shoulder = float(spec["shoulder"])

    z3 = 0.045  # Linear Zone III (~2 stops below 18% middle gray)
    x = np.maximum(lin.astype(np.float32, copy=False), 0.0)
    luma = np.maximum(np.sum(x * LUMA, axis=-1, keepdims=True), 1e-6)

    # Smooth Hermite weight: 0 below Zone I (0.012), 1 at/above Zone III (0.045)
    t = np.clip((luma - 0.012) / (z3 - 0.012), 0.0, 1.0)
    w = t * t * (3.0 - 2.0 * t)

    # Expand or contract luminance relative to Zone III anchor
    target_luma = z3 * np.power(np.maximum(luma / z3, 1e-6), gamma)
    new_luma = luma * (1.0 - w) + target_luma * w

    # Gentle highlight shoulder compression for N-1 / N-2 (and safety rolloff on N+2)
    if shoulder > 0.001:
        knee = 0.55 if gamma < 1.0 else 1.15
        excess = np.maximum(0.0, new_luma - knee)
        new_luma = np.where(
            new_luma > knee,
            knee + excess / (1.0 + shoulder * excess),
            new_luma,
        )

    scale = np.clip(new_luma / luma, 0.25, 4.0)
    return np.maximum(0.0, x * scale)


def develop_frame(
    image_input,
    film_key="portra400",
    ev_adjust=0.0,
    halation_mult=1.0,
    grain_mult=1.0,
    grain_asa="auto",
    vignette_mult=1.0,
    shadows=0.0,
    mids=0.0,
    highlights=0.0,
    curve=None,
    add_date=False,
    max_dim=None,
    rotate=0,
    flip_h=False,
    flip_v=False,
    straighten=0.0,
    keystone_v=0.0,
    keystone_h=0.0,
    crop_rect=None,
    auto_crop_straighten=True,
    return_float=False,
    grain_seed=None,
    dev_process="standard",
    denoise_luma=0.0,
    denoise_chroma=0.0,
    defringe=0.0,
    local_masks=None,
    dust_spots=None,
    sharpen_mode="off",
    sharpen_amount=1.0,
    film_strength=1.0,
    sim_temp=0.0,
    sim_tint=0.0,
    bw_filter="none",
    zone_dev="N",
    enlarger_head="standard",
    paper_dev="neutral",
    paper_base="none",
    bw_grade00=0.0,
    bw_grade5=0.0,
    bw_preflash=0.0,
    toner_shadows="none",
    toner_shadows_amt=0.0,
    toner_highlights="none",
    toner_highlights_amt=0.0,
    farmer_bleach=0.0,
    upscale_factor=1.0,
    upscale_mode="ibp",
    deconv_radius=1.0,
    deconv_amount=0.0,
    clarity=0.0,
    texture=0.0,
    dehaze=0.0,
    protect_skin=False,
    output_sharpen_media="off",
    halo_suppress=0.5,
    dejpeg=0.0,
):
    """Full development pipeline: image/path in -> developed PIL Image out."""
    has_geom = bool(
        rotate
        or flip_h
        or flip_v
        or abs(float(straighten or 0.0)) > 0.01
        or abs(float(keystone_v or 0.0)) > 0.01
        or abs(float(keystone_h or 0.0)) > 0.01
        or normalize_crop_rect(crop_rect) is not None
    )
    if isinstance(image_input, (str, Path)):
        lin = load_image_linear(
            image_input,
            max_dim=max_dim,
            rotate=rotate,
            flip_h=flip_h,
            flip_v=flip_v,
            straighten=straighten,
            keystone_v=keystone_v,
            keystone_h=keystone_h,
            crop_rect=crop_rect,
            auto_crop_straighten=auto_crop_straighten,
        )
    elif isinstance(image_input, Image.Image):
        if max_dim is not None and max(image_input.size) > max_dim:
            scale = max_dim / max(image_input.size)
            new_size = (int(image_input.width * scale), int(image_input.height * scale))
            image_input = image_input.resize(new_size, Image.Resampling.LANCZOS)
        lin = srgb_to_linear(np.asarray(image_input, dtype=np.float32) / 255.0)
        if has_geom:
            lin = apply_geometry(
                lin,
                rotate=rotate,
                flip_h=flip_h,
                flip_v=flip_v,
                straighten=straighten,
                keystone_v=keystone_v,
                keystone_h=keystone_h,
                crop_rect=crop_rect,
                auto_crop_straighten=auto_crop_straighten,
            )
    else:
        lin = np.array(image_input, dtype=np.float32)
        if has_geom:
            lin = apply_geometry(
                lin,
                rotate=rotate,
                flip_h=flip_h,
                flip_v=flip_v,
                straighten=straighten,
                keystone_v=keystone_v,
                keystone_h=keystone_h,
                crop_rect=crop_rect,
                auto_crop_straighten=auto_crop_straighten,
            )

    # 0. Pre-development digital cleanup (defringe, denoise, de-JPEG/anti-moire, pinpoint dust heal, local dodge/burn)
    if float(defringe or 0.0) > 0.005:
        lin = apply_defringe(lin, strength=float(defringe))
    if float(dejpeg or 0.0) > 0.01:
        from .superres import apply_dejpeg_antimoire

        lin = apply_dejpeg_antimoire(lin, strength=float(dejpeg))
    if float(denoise_luma or 0.0) > 0.005 or float(denoise_chroma or 0.0) > 0.005:
        lin = apply_digital_denoise(
            lin,
            luma_strength=float(denoise_luma or 0.0),
            chroma_strength=float(denoise_chroma or 0.0),
        )
    if dust_spots:
        lin_clipped = np.clip(lin, 0.0, 1.0)
        lin_healed = apply_dust_spot_healing(lin_clipped, dust_spots)
        lin = np.where(lin > 1.0, lin, lin_healed)
    if local_masks:
        lin = apply_local_dodge_burn(lin, local_masks)

    film = get_film(film_key)
    proc_spec = DEV_PROCESSES.get(str(dev_process or "standard"), DEV_PROCESSES["standard"])

    # 1. Exposure compensation (film stock + user EV + chemical push/pull process)
    total_ev = film.get("ev", 0.0) + ev_adjust + proc_spec["ev_offset"]
    if abs(total_ev) > 1e-4:
        lin = lin * (2.0 ** total_ev)

    # 1-wb. Pre-emulsion white balance (Temperature & Tint in linear light)
    if abs(float(sim_temp or 0.0)) > 1e-4 or abs(float(sim_tint or 0.0)) > 1e-4:
        t_val = max(-1.0, min(1.0, float(sim_temp or 0.0)))
        g_val = max(-1.0, min(1.0, float(sim_tint or 0.0)))
        r_gain = 2.0 ** (0.35 * t_val + 0.15 * g_val)
        g_gain = 2.0 ** (-0.25 * g_val)
        b_gain = 2.0 ** (-0.35 * t_val + 0.15 * g_val)
        luma_scale = 0.2126 * r_gain + 0.7152 * g_gain + 0.0722 * b_gain
        wb_gains = np.array([r_gain, g_gain, b_gain], dtype=np.float32) / max(luma_scale, 1e-4)
        lin = np.maximum(0.0, lin * wb_gains)

    # 1-dehaze. Atmospheric Dehaze / Vintage lens veiling-flare removal in linear light
    if abs(float(dehaze or 0.0)) > 0.01:
        from .superres import apply_optical_dehaze

        lin = apply_optical_dehaze(lin, amount=float(dehaze))

    # 1a. Compensating developer highlight shoulder protection & shadow luminosity (D-23, Pyro, Windisch)
    if proc_spec["compensating"] > 0.01:
        comp = float(proc_spec["compensating"])
        lin = np.where(
            lin > 0.55,
            0.55 + (lin - 0.55) / (1.0 + comp * 0.45 * np.maximum(0.0, lin - 0.55)),
            lin,
        )
    if float(proc_spec.get("shadow_lift", 0.0)) > 0.005:
        s_lift = float(proc_spec["shadow_lift"])
        luma_s = np.sum(lin * LUMA, axis=-1, keepdims=True)
        sh_mask = np.clip((0.20 - luma_s) / 0.20, 0.0, 1.0) ** 1.4
        lin = np.maximum(0.0, lin * (1.0 + s_lift * sh_mask))

    # 1a-zone. Zone System N-2..N+2 development (pivoted around Zone III)
    if zone_dev and str(zone_dev).strip().upper() != "N":
        lin = apply_zone_system_dev(lin, zone_dev=str(zone_dev))

    # 1b. Tonal zones (shadows / midtones / highlights) as linear exposure
    if abs(shadows) > 1e-4 or abs(mids) > 1e-4 or abs(highlights) > 1e-4:
        lin = apply_tonal_zones(lin, shadows=shadows, mids=mids, highlights=highlights)

    # 2. Vignette
    if vignette_mult > 0.001:
        lin = apply_vignette(lin, strength=vignette_mult)

    # 3. Halation
    hal_strength = film.get("halation", 0.0) * halation_mult
    if hal_strength > 0.01:
        lin = apply_halation(
            lin,
            strength=hal_strength,
            threshold=film.get("hal_thr", 0.75),
            tint=film.get("hal_tint", (1.0, 0.28, 0.06))
        )

    # 3b. Optical B&W lens filter (#8 Yellow, #21 Orange, #25 Red, #11 Green, #47 Blue)
    bw_key = str(bw_filter or "none").strip().lower()
    lin_for_film = lin
    if film.get("mono") and bw_key in BW_OPTICAL_FILTERS:
        filt_mix = np.array(BW_OPTICAL_FILTERS[bw_key], dtype=np.float32)
        y_filt = np.maximum(0.0, np.sum(lin * filt_mix, axis=-1, keepdims=True))
        lin_for_film = np.repeat(y_filt, 3, axis=-1)

    # 4. Color / Film Look
    lut_file = film.get("lut_file")
    if lut_file:
        lut_path = Path(lut_file)
        cube_path = lut_path if lut_path.is_absolute() else (LUT_DIR / lut_file)
    else:
        cube_path = None

    if cube_path and cube_path.is_file():
        lut_obj = load_lut(str(cube_path), space=film.get("lut_space", "srgb"))
        display = lut_obj.apply(lin_for_film)
    else:
        # Mathematical curve model
        if film.get("mono"):
            mono_mix = np.array(film["mono"], dtype=np.float32)
            luma_chan = np.sum(lin_for_film * mono_mix, axis=-1)
            c0, p0 = film["contrast"][0], film["pivot"][0]
            b0, w0 = film["black"][0], film["white"][0]
            curve_val = apply_characteristic_curve(luma_chan, c0, p0, b0, w0)
            display = np.stack([curve_val] * 3, axis=-1)
        else:
            y = np.sum(lin_for_film * LUMA, axis=-1, keepdims=True)
            sat = film.get("sat", 1.0)
            lin_sat = np.maximum(0.0, y + (lin_for_film - y) * sat)

            contrast = film["contrast"]
            pivot = film["pivot"]
            black = film["black"]
            white = film["white"]

            channels = []
            for c in range(3):
                c_slope = contrast[c] if len(contrast) > c else contrast[0]
                c_piv = pivot[c] if len(pivot) > c else pivot[0]
                c_blk = black[c] if len(black) > c else black[0]
                c_wht = white[c] if len(white) > c else white[0]
                channels.append(apply_characteristic_curve(lin_sat[..., c], c_slope, c_piv, c_blk, c_wht))
            display = np.stack(channels, axis=-1)

            if film.get("hues"):
                display = shift_hues(display, film["hues"])

    display = np.clip(display, 0.0, 1.0)

    # 4-strength. Blend film emulation strength (0.0 = neutral sRGB, 1.0 = full emulation)
    strength = max(0.0, min(1.0, float(film_strength if film_strength is not None else 1.0)))
    if strength < 0.999:
        neutral_srgb = linear_to_srgb(np.clip(lin, 0.0, 1.0))
        display = np.clip(neutral_srgb * (1.0 - strength) + display * strength, 0.0, 1.0)

    # 4a. Chemical push/pull contrast & developer acutance
    if abs(proc_spec["contrast_mult"] - 1.0) > 0.005:
        display = np.clip(0.45 + (display - 0.45) * float(proc_spec["contrast_mult"]), 0.0, 1.0)
    if proc_spec["acutance"] > 0.01:
        display = apply_optical_sharpen(display, mode="lab", amount=float(proc_spec["acutance"]))

    # 4a-head. Enlarger head optical transfer (Condenser Callier vs. Diffuser Cold Light)
    head_spec = ENLARGER_HEADS.get(str(enlarger_head or "standard").strip().lower(), ENLARGER_HEADS["standard"])
    if enlarger_head and str(enlarger_head).strip().lower() != "standard":
        display = apply_enlarger_head(display, head=str(enlarger_head))

    # 4a-print. B&W Darkroom Printmaking (Split-Grade 00/5, Pre-flash, Paper Developer & Paper Base)
    display = apply_bw_darkroom_print(
        display,
        paper_dev=paper_dev,
        paper_base=paper_base,
        bw_grade00=bw_grade00,
        bw_grade5=bw_grade5,
        bw_preflash=bw_preflash,
    )

    # 4a-farmer. Global Farmer's Reducer bleaching (Jay Dusard)
    if float(farmer_bleach or 0.0) > 0.005:
        display = apply_farmer_bleach(display, amount=float(farmer_bleach))

    # 4a-toner. Sequential Chemical Dual-Toning (Tim Rudman)
    display = apply_dual_toning(
        display,
        toner_shadows=toner_shadows,
        toner_shadows_amt=toner_shadows_amt,
        toner_highlights=toner_highlights,
        toner_highlights_amt=toner_highlights_amt,
    )

    # 4b. User tone curve (display-referred: same space as a darkroom curve)
    if curve:
        display = apply_user_curves(display, curve)

    # 4b-detail. Richardson-Lucy Optical Deconvolution + Multi-scale Clarity & Texture (pre-grain)
    if float(deconv_amount or 0.0) > 0.01:
        from .superres import apply_richardson_lucy_deconv

        display = apply_richardson_lucy_deconv(
            display,
            radius=float(deconv_radius or 1.0),
            amount=float(deconv_amount),
        )
    if abs(float(clarity or 0.0)) > 0.01 or abs(float(texture or 0.0)) > 0.01:
        from .superres import apply_clarity_and_texture

        display = apply_clarity_and_texture(
            display,
            clarity=float(clarity or 0.0),
            texture=float(texture or 0.0),
            protect_skin=bool(protect_skin),
        )

    # 4c. Pre-grain Optical Upscaling & Super-Resolution (only on full-res render, so grain renders at final res)
    if max_dim is None and float(upscale_factor or 1.0) > 1.01 and str(upscale_mode or "ibp").lower() != "off":
        from .superres import compute_target_dimensions, upscale_float_rgb

        out_w, out_h, _ = compute_target_dimensions(
            display.shape[1], display.shape[0], upscale_factor=float(upscale_factor)
        )
        if out_w > display.shape[1] or out_h > display.shape[0]:
            display = upscale_float_rgb(display, out_w, out_h, mode=str(upscale_mode or "ibp"))

    # 5. Film Grain (modulated by developer, enlarger head Callier/Diffuser, and Pyro highlight stain)
    base_grain_amt, base_grain_size = resolve_grain_profile(film, grain_asa=grain_asa)
    grain_amt = base_grain_amt * grain_mult * float(proc_spec["grain_mult"]) * float(head_spec["grain_mult"])
    if grain_amt > 0.001:
        seed = grain_seed if grain_seed is not None else _stable_grain_seed(image_input, film_key)
        eff_grain_size = (
            base_grain_size
            * float(proc_spec.get("clump_mult", 1.0))
            * (1.0 + 0.12 * max(0.0, float(grain_mult) - 1.0))
        )
        grain_chroma = 0.0 if film.get("mono") else 0.22
        display = apply_grain(
            display,
            amount=grain_amt,
            size=eff_grain_size,
            seed=seed,
            chroma=grain_chroma,
            highlight_mask=float(proc_spec.get("pyro_mask", 0.0)),
        )

    # 6. Optical Softness & Output Sharpening
    soft = film.get("soft", 0.0)
    if soft > 0.4:
        display = scipy.ndimage.gaussian_filter(display, sigma=[soft * 0.4, soft * 0.4, 0.0])

    if sharpen_mode and sharpen_mode != "off" and float(sharpen_amount or 0.0) > 0.01:
        display = apply_optical_sharpen(display, mode=str(sharpen_mode), amount=float(sharpen_amount))
    if output_sharpen_media and str(output_sharpen_media).strip().lower() != "off":
        from .superres import apply_output_sharpen_media

        display = apply_output_sharpen_media(
            display,
            media=str(output_sharpen_media),
            amount=1.0,
            halo_suppress=float(halo_suppress if halo_suppress is not None else 0.5),
        )

    display_clamped = np.clip(display, 0.0, 1.0).astype(np.float32)
    # np.rint rounds to nearest; a plain astype(uint8) truncates and applies a
    # systematic -0.5 LSB bias to every pixel of every exported master.
    out_img = Image.fromarray(np.rint(display_clamped * 255.0).astype(np.uint8))

    if add_date:
        out_img = draw_date_stamp(out_img)
        if return_float:
            display_clamped = np.asarray(out_img.convert("RGB"), dtype=np.float32) / 255.0

    if return_float:
        return out_img, display_clamped
    return out_img
