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
from .films import LUT_DIR, get_film
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

    Implemented with a single branch instead of ``np.where``: ``np.where``
    evaluates *both* arms, so a 24 MP frame allocated four extra float32
    temporaries (≈1.2 GB of peak RSS) on every conversion, and the engine
    converts 4-8 times per frame.
    """
    srgb = np.maximum(np.asarray(srgb, dtype=np.float32), 0.0)
    out = np.empty_like(srgb, dtype=np.float32)
    low = srgb <= 0.04045
    np.divide(srgb, 12.92, out=out, where=low)
    high = ~low
    if high.any():
        out[high] = np.power((srgb[high] + 0.055) / 1.055, 2.4)
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
        out[high] = 1.055 * np.power(lin[high], 1 / 2.4) - 0.055
    return out


def apply_characteristic_curve(x, slope, pivot, black, white):
    """Logistic characteristic response curve in log2 exposure around 18% mid grey."""
    x = np.maximum(x, 1e-6)
    xx = np.log2(x / 0.18) - pivot
    k = 4.0 * slope / (white - black)
    return black + (white - black) / (1.0 + np.exp(-k * xx))


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


def apply_geometry(arr, rotate=0, flip_h=False):
    """Apply lossless 90-degree rotations (clockwise degrees: 0, 90, 180, 270) and horizontal mirror."""
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
    return np.ascontiguousarray(out)


def load_image_linear(path, max_dim=None, rotate=0, flip_h=False):
    """Loads a RAW or standard image into scene-linear float32 RGB, utilizing RAM cache for previews."""
    path = Path(path).resolve()
    if max_dim is not None and path.is_file() and _cacheable_preview(max_dim):
        mtime_ns = path.stat().st_mtime_ns
        base = _load_image_linear_cached(str(path), mtime_ns, int(max_dim)).copy()
    else:
        base = _decode_image_linear_uncached(path, max_dim=max_dim)
    if rotate or flip_h:
        base = apply_geometry(base, rotate=rotate, flip_h=flip_h)
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


def save_tiff_16bit_rgb(float_srgb: np.ndarray, target_path: Path, analog_meta: dict | None = None) -> None:
    """Write a true 48-bit (16-bit per channel uint16 RGB) lossless Adobe-Deflate archival TIFF."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    u16 = np.clip(np.rint(np.clip(float_srgb, 0.0, 1.0) * 65535.0), 0, 65535).astype("<u2")
    u16 = np.ascontiguousarray(u16)
    h, w = u16.shape[:2]

    # Compress in horizontal strips (~64 rows per strip) for fast random-access & universal viewer support
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

    icc_bytes = _get_srgb_icc_bytes()

    # Build sorted TIFF 6.0 IFD entries: (tag, field_type, count, raw_data_bytes)
    # Types: 2=ASCII, 3=SHORT (uint16), 4=LONG (uint32), 5=RATIONAL (2x uint32), 7=UNDEFINED
    raw_tags: list[tuple[int, int, int, bytes]] = [
        (256, 4, 1, struct.pack("<I", w)),  # ImageWidth
        (257, 4, 1, struct.pack("<I", h)),  # ImageLength
        (258, 3, 3, struct.pack("<HHH", 16, 16, 16)),  # BitsPerSample = (16, 16, 16)
        (259, 3, 1, struct.pack("<H", 8)),  # Compression = 8 (Adobe Deflate)
        (262, 3, 1, struct.pack("<H", 2)),  # PhotometricInterpretation = 2 (RGB)
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

    # Placeholders for 273 StripOffsets & 279 StripByteCounts (filled once header size is known)
    raw_tags.extend(
        [
            (273, 4, num_strips, b"\x00" * (4 * num_strips)),  # StripOffsets
            (274, 3, 1, struct.pack("<H", 1)),  # Orientation = 1
            (277, 3, 1, struct.pack("<H", 3)),  # SamplesPerPixel = 3
            (278, 4, 1, struct.pack("<I", rows_per_strip)),  # RowsPerStrip
            (279, 4, num_strips, struct.pack(f"<{num_strips}I", *[len(b) for b in strip_blobs])),  # StripByteCounts
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
        raw_tags.append((34675, 7, len(icc_bytes), icc_bytes))  # InterColorProfile (sRGB IEC61966-2.1)

    raw_tags.sort(key=lambda item: item[0])
    num_entries = len(raw_tags)
    ifd_offset = 8
    extra_start = ifd_offset + 2 + num_entries * 12 + 4

    # First pass to calculate exact byte offset where compressed strip payloads start
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

    # Replace StripOffsets tag 273 with exact offsets
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


def save_output_image(
    pil_img,
    target_path,
    source_path=None,
    quality=96,
    float_srgb: np.ndarray | None = None,
    analog_meta: dict | None = None,
):
    """Save developed image in JPG (4:4:4 + EXIF), PNG, or 16-bit (48-bit RGB) archival TIFF.

    The file is written to a temporary sibling and then moved into place, so an
    interrupted export can never leave a truncated master behind.
    """
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
            return

        exif_bytes = build_export_exif_bytes(source_path=source_path, analog_meta=analog_meta)
        icc_bytes = _get_srgb_icc_bytes()

        if ext == ".png":
            save_kwargs = {"format": "PNG", "compress_level": 4, "icc_profile": icc_bytes}
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
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


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
    over = np.maximum(0.0, luma - threshold)
    
    # 0.6% - 1.0% of frame width blur radius
    sigma = max(2.0, lin.shape[1] * 0.008)
    glow = scipy.ndimage.gaussian_filter(over, sigma=sigma)
    
    tint_arr = np.array(tint, dtype=np.float32)[None, None, :]
    glow_rgb = glow[..., None] * tint_arr * (strength * 0.35)
    return lin + glow_rgb


def apply_grain(rgb, amount=0.02, size=1.0, seed=None):
    """Adds natural midtone-peaking analog film grain.

    The RNG is local and optionally seeded. The previous implementation drew
    from NumPy's *global* RNG, which meant every re-render produced a different
    grain pattern: the preview visibly "boiled" while dragging a slider and the
    exported master never matched the frame the photographer had approved. Worse,
    under ThreadPoolExecutor the pattern of a given frame depended on thread
    scheduling, so two exports of the same roll differed from each other.
    """
    if amount <= 0.001:
        return rgb

    rng = np.random.default_rng(seed)
    h, w = rgb.shape[:2]
    if size > 1.05:
        nh, nw = max(1, int(h / size)), max(1, int(w / size))
        small_noise = rng.normal(0.0, 1.0, (nh, nw)).astype(np.float32)
        noise_img = Image.fromarray(small_noise)
        noise = np.asarray(noise_img.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32)
    else:
        noise = rng.normal(0.0, 1.0, (h, w)).astype(np.float32)

    luma = np.sum(rgb * LUMA, axis=-1, keepdims=True)
    weight = 4.0 * luma * np.maximum(0.0, 1.0 - luma)  # Mid-tone peaking

    noisy_rgb = rgb + noise[..., None] * (amount * weight)
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


def develop_frame(
    image_input,
    film_key="portra400",
    ev_adjust=0.0,
    halation_mult=1.0,
    grain_mult=1.0,
    vignette_mult=1.0,
    add_date=False,
    max_dim=None,
    rotate=0,
    flip_h=False,
    return_float=False,
    grain_seed=None,
):
    """Full development pipeline: image/path in -> developed PIL Image out."""
    if isinstance(image_input, (str, Path)):
        lin = load_image_linear(image_input, max_dim=max_dim, rotate=rotate, flip_h=flip_h)
    elif isinstance(image_input, Image.Image):
        if max_dim is not None and max(image_input.size) > max_dim:
            scale = max_dim / max(image_input.size)
            new_size = (int(image_input.width * scale), int(image_input.height * scale))
            image_input = image_input.resize(new_size, Image.Resampling.LANCZOS)
        lin = srgb_to_linear(np.asarray(image_input, dtype=np.float32) / 255.0)
        if rotate or flip_h:
            lin = apply_geometry(lin, rotate=rotate, flip_h=flip_h)
    else:
        lin = np.array(image_input, dtype=np.float32)
        if rotate or flip_h:
            lin = apply_geometry(lin, rotate=rotate, flip_h=flip_h)

    film = get_film(film_key)
    
    # 1. Exposure compensation
    total_ev = film.get("ev", 0.0) + ev_adjust
    if abs(total_ev) > 1e-4:
        lin = lin * (2.0 ** total_ev)
        
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
        
    # 4. Color / Film Look
    lut_file = film.get("lut_file")
    cube_path = LUT_DIR / lut_file if lut_file else None
    
    if cube_path and cube_path.is_file():
        lut_obj = load_lut(str(cube_path), space=film.get("lut_space", "srgb"))
        display = lut_obj.apply(lin)
    else:
        # Mathematical curve model
        if film.get("mono"):
            mono_mix = np.array(film["mono"], dtype=np.float32)
            luma_chan = np.sum(lin * mono_mix, axis=-1)
            c0, p0 = film["contrast"][0], film["pivot"][0]
            b0, w0 = film["black"][0], film["white"][0]
            curve_val = apply_characteristic_curve(luma_chan, c0, p0, b0, w0)
            display = np.stack([curve_val] * 3, axis=-1)
        else:
            y = np.sum(lin * LUMA, axis=-1, keepdims=True)
            sat = film.get("sat", 1.0)
            lin_sat = np.maximum(0.0, y + (lin - y) * sat)
            
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
    
    # 5. Film Grain
    grain_amt = film.get("grain", 0.015) * grain_mult
    if grain_amt > 0.001:
        seed = grain_seed if grain_seed is not None else _stable_grain_seed(image_input, film_key)
        display = apply_grain(display, amount=grain_amt, size=film.get("grain_size", 1.0), seed=seed)
        
    # 6. Optical Softness
    soft = film.get("soft", 0.0)
    if soft > 0.4:
        display = scipy.ndimage.gaussian_filter(display, sigma=[soft * 0.4, soft * 0.4, 0.0])
        
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
