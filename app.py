"""Flask backend application for Haluro — Laboratorio Analógico Digital.
Provides REST API for 72-stock film emulation, optical negative density inversion,
real-time cached previews, lossless multi-format export, and contact sheets.
"""

import base64
import functools
import io
import json
import logging
import math
import os
import secrets
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from engine import APP_NAME, __version__, about_payload
from engine.contact_sheet import generate_contact_sheet
from engine.films import LUT_DIR, get_film, list_films
from engine.negative_inverter import (
    BW_TONING_PROFILES,
    COLOR_METHODS,
    LIGHT_SOURCE_MATRICES,
    MINILAB_PROFILES,
    PRINT_FINISHES,
    SCAN_SOURCES,
    SHARPEN_MODES,
    TONE_VARIANTS,
    analyze_roll_calibration,
    auto_balance_scene_wb,
    auto_detect_film_base,
    compute_neutral_wb_from_point,
    linear_rgb_to_hex,
    list_bw_toners,
    list_print_finishes,
    process_negative_to_image,
)
from engine.negative_inverter import (
    list_profiles as list_negative_profiles,
)
from engine.pipeline import (
    HEIF_EXTENSIONS,
    RAW_EXTENSIONS,
    develop_frame,
    format_analog_caption,
    get_srgb_icc_bytes,
    linear_to_srgb,
    load_image_linear,
    save_output_image,
)
from engine.platform_io import (
    choose_save_path_dialog,
    get_downloads_dir,
    get_platform_tag,
    get_resource_root,
    get_runtime_diagnostics,
    get_user_data_root,
    open_directory,
    reveal_in_file_manager,
)
from engine.updater import check_for_updates, open_external_url

logger = logging.getLogger(__name__)

RESOURCE_ROOT = get_resource_root()
USER_DATA_ROOT = get_user_data_root()
SAMPLES_DIR = (RESOURCE_ROOT / "samples").resolve()
UPLOAD_DIR = (USER_DATA_ROOT / "uploads").resolve()
DEVELOPED_DIR = (USER_DATA_ROOT / "developed").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEVELOPED_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_OUTPUT_EXTS = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "tiff": ".tiff", "tif": ".tiff"}
ALLOWED_INPUT_EXTS = RAW_EXTENSIONS | HEIF_EXTENSIONS | {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}

# Workspace hygiene: uploads are transient working copies, not an archive.
UPLOAD_RETENTION_DAYS = 30
UPLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def _prune_workspace() -> None:
    """Drop stale uploads and trim the workspace to a size budget.

    The upload folder grew without bound (467 MB on a single workstation) and
    every export added another preview to the developed archive.
    """
    cutoff = time.time() - (UPLOAD_RETENTION_DAYS * 86400)
    try:
        entries = sorted(UPLOAD_DIR.glob("*"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return

    total = 0
    survivors = []
    for item in entries:
        try:
            st = item.stat()
        except OSError:
            continue
        if item.is_file() and st.st_mtime < cutoff:
            try:
                item.unlink()
            except OSError:
                pass
            continue
        total += st.st_size if item.is_file() else 0
        survivors.append((st.st_mtime, item))

    for _mtime, item in survivors:
        if total <= UPLOAD_MAX_BYTES:
            break
        try:
            size = item.stat().st_size
            item.unlink()
            total -= size
        except OSError:
            continue


_prune_workspace()

app = Flask(
    __name__,
    template_folder=str(RESOURCE_ROOT / "templates"),
    static_folder=str(RESOURCE_ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB max per upload

# --- Local-only hardening ----------------------------------------------------
# The backend only ever listens on 127.0.0.1, but a browser on the same machine
# (or a malicious page) can still issue cross-site requests against it, and a
# DNS-rebinding attack can make the browser believe the app lives on an
# attacker-controlled origin. Both are neutralised here:
#   * TRUSTED_HOSTS rejects any request whose Host header is not loopback.
#   * API_TOKEN must be echoed in the X-Haluro-Token header on every
#     state-changing call; the frontend injects it from a per-process secret.
API_TOKEN = secrets.token_urlsafe(32)
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", "::1"]

# Guard against decompression bombs: Pillow refuses images above this size.
Image.MAX_IMAGE_PIXELS = 120_000_000  # 120 MP ≈ 480 MB per float32 RGB array

# Maximum number of frames a single batch request may queue.
MAX_BATCH_FRAMES = 200
# Maximum number of concurrent full-resolution developments (memory bound).
MAX_FULL_RES_WORKERS = 2


@app.after_request
def _apply_security_headers(response):
    """Apply defense-in-depth HTTP security headers to all responses.

    Self-hosted fonts & assets ensure 100% offline privacy with zero external telemetry.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-src 'none'; "
        "frame-ancestors 'none';",
    )
    return response


@app.errorhandler(413)
def _handle_payload_too_large(_err):
    return jsonify({"error": "El archivo supera el límite máximo permitido (300 MB)."}), 413


class InvalidRequest(ValueError):
    """Raised when a client-supplied parameter is malformed or out of range."""


@app.errorhandler(InvalidRequest)
def _handle_invalid_request(err):
    """Malformed client input is a 400, never a 500."""
    return jsonify({"error": str(err) or "Parámetro no válido."}), 400


@app.before_request
def _guard_local_only():
    """Reject requests that do not come from the local application itself.

    Blocks DNS rebinding (Host header is not loopback) and cross-site requests
    forged from a page the photographer happens to have open in the same
    browser (Origin header points somewhere else).
    """
    hostname = (request.host or "").split(":")[0].lower().strip("[]")
    if hostname not in ALLOWED_LOOPBACK_HOSTS:
        return jsonify({"error": "Origen no permitido."}), 403

    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin:
            origin_host = (urlparse(origin).hostname or "").lower()
            if origin_host not in ALLOWED_LOOPBACK_HOSTS:
                return jsonify({"error": "Origen no permitido."}), 403
        if request.headers.get("X-Haluro-Token") != API_TOKEN:
            return jsonify({"error": "Sesión local no válida. Recarga la aplicación."}), 403
    return None


@app.errorhandler(Exception)
def _handle_unexpected_exception(err):
    if isinstance(err, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": err.description}), err.code
        return err
    logger.exception("Unhandled error on %s %s", request.method, request.path)
    return jsonify({"error": "Error interno en el laboratorio de procesado."}), 500


# -------------------------------------------------------------
# SECURITY & CACHING HELPERS
# -------------------------------------------------------------

def _sanitize_filename(raw_name):
    """Sanitize uploaded filename while preserving valid extensions."""
    raw_path = Path(raw_name or "frame.jpg")
    ext = raw_path.suffix.lower()
    clean = secure_filename(raw_path.name)
    if not clean or clean.startswith("."):
        clean = f"captura_{uuid.uuid4().hex[:8]}{ext or '.jpg'}"
    return clean


def _unique_upload_path(filename: str) -> Path:
    """Return a non-colliding path inside UPLOAD_DIR so duplicate basenames never overwrite prior scans."""
    candidate = UPLOAD_DIR / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    ext = Path(filename).suffix
    idx = 2
    while True:
        cand = UPLOAD_DIR / f"{stem}_{idx}{ext}"
        if not cand.exists():
            return cand
        idx += 1


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# -------------------------------------------------------------
# PARAMETER VALIDATION HELPERS
# -------------------------------------------------------------

def _num(source, key, default, lo=None, hi=None):
    """Read a float from a mapping, rejecting non-numeric or non-finite values.

    Raises InvalidRequest (HTTP 400) instead of letting a ValueError escape as
    a 500, and clamps the result to the range the UI can actually produce.
    """
    raw = source.get(key, default) if isinstance(source, dict) else default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise InvalidRequest(f"El valor de «{key}» no es numérico.") from None
    if not math.isfinite(value):
        raise InvalidRequest(f"El valor de «{key}» debe ser un número finito.")
    if lo is not None:
        value = max(float(lo), value)
    if hi is not None:
        value = min(float(hi), value)
    return value


def _int(source, key, default, lo=None, hi=None):
    """Read an int from a mapping with the same guarantees as :func:`_num`."""
    raw = source.get(key, default) if isinstance(source, dict) else default
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        raise InvalidRequest(f"El valor de «{key}» no es un número entero.") from None
    if lo is not None:
        value = max(int(lo), value)
    if hi is not None:
        value = min(int(hi), value)
    return value


def _canonical_film_key(raw_key) -> str:
    """Return the catalogue key for a film, never the raw client-supplied string.

    The raw value used to be interpolated straight into output paths, which
    allowed a traversal payload to write anywhere on the filesystem.
    """
    key = str(raw_key or "").strip()
    film = get_film(key)
    return str(film.get("key") or "portra400")


def _canonical_profile_key(raw_key) -> str:
    """Return a valid minilab/negative profile key or the safe default."""
    key = str(raw_key or "").strip()
    return key if key in MINILAB_PROFILES else "frontier"


def _bounded_frames(raw_filenames):
    """Normalise and cap the frame list of a batch request.

    The list used to be forwarded verbatim, so a single request could queue
    thousands of full-resolution developments and exhaust the machine's RAM.
    """
    if not isinstance(raw_filenames, (list, tuple)):
        return []
    frames = []
    for item in raw_filenames:
        if not isinstance(item, str):
            continue
        name = Path(item).name
        if name:
            frames.append(name)
        if len(frames) >= MAX_BATCH_FRAMES:
            break
    return frames


def _safe_output_path(base_dir: Path, *parts: str) -> Path:
    """Join sanitised components onto a base directory, refusing to escape it.

    Every component is reduced to a bare file name via ``secure_filename`` and
    the result is verified to stay inside ``base_dir``.
    """
    safe_parts = []
    for part in parts:
        cleaned = secure_filename(str(part or "").strip())
        if not cleaned or cleaned in (".", ".."):
            raise InvalidRequest("Nombre de archivo de salida no válido.")
        safe_parts.append(cleaned)
    candidate = base_dir.joinpath(*safe_parts)
    if not _is_within(candidate, base_dir):
        raise InvalidRequest("Ruta de salida fuera del directorio permitido.")
    return candidate


def _resolve_source_file(filename, fallback_name=None):
    """Safely locate a source file inside uploads/ or samples/ without path traversal."""
    safe_name = Path(filename or "").name
    if safe_name:
        cand_upload = (UPLOAD_DIR / safe_name).resolve()
        if _is_within(cand_upload, UPLOAD_DIR) and cand_upload.is_file():
            return cand_upload
        cand_sample = (SAMPLES_DIR / safe_name).resolve()
        if _is_within(cand_sample, SAMPLES_DIR) and cand_sample.is_file():
            return cand_sample

    if fallback_name:
        fb = (SAMPLES_DIR / fallback_name).resolve()
        if _is_within(fb, SAMPLES_DIR) and fb.is_file():
            return fb
    return None


def _normalize_ext(fmt_str):
    fmt = str(fmt_str or "jpg").lower().lstrip(".")
    return ALLOWED_OUTPUT_EXTS.get(fmt, ".jpg")


def _validate_destination_path(raw_path: str) -> tuple[Path | None, str | None]:
    """Validate user export destination path: must have an allowed image extension and a writable directory."""
    if not raw_path or not isinstance(raw_path, str):
        return None, "Ruta de destino inválida o vacía."
    try:
        dest = Path(raw_path).expanduser().resolve()
    except Exception as exc:
        return None, f"Ruta de destino no válida: {exc}"

    ext = dest.suffix.lower()
    if ext not in ALLOWED_OUTPUT_EXTS.values() and ext not in {".jpg", ".jpeg", ".png", ".tiff", ".tif"}:
        return None, f"Extensión de archivo no permitida ({ext}). Use .jpg, .png o .tiff."

    parent = dest.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, f"No se puede crear la carpeta de destino: {exc}"

    return dest, None


@functools.lru_cache(maxsize=24)
def _cached_original_b64(resolved_path_str, mtime_ns, max_dim, rotate, flip_h, crop_milli=0):
    """Encode original reference preview once and serve from RAM on subsequent slider moves."""
    lin = load_image_linear(resolved_path_str, max_dim=max_dim, rotate=rotate, flip_h=flip_h)
    if crop_milli > 2:
        c_p = crop_milli / 1000.0
        h, w = lin.shape[:2]
        cy, cx = int(h * c_p), int(w * c_p)
        if h - 2 * cy > 32 and w - 2 * cx > 32:
            lin = lin[cy:h - cy, cx:w - cx]
    srgb = (np.clip(linear_to_srgb(lin), 0.0, 1.0) * 255.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(srgb).save(buf, format="JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


@functools.lru_cache(maxsize=64)
def _cached_thumb_bytes(resolved_path_str, mtime_ns):
    """Generate and cache crisp 240px JPEG filmstrip thumbnail."""
    lin = load_image_linear(resolved_path_str, max_dim=240)
    srgb = (np.clip(linear_to_srgb(lin), 0.0, 1.0) * 255.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(srgb).save(buf, format="JPEG", quality=82)
    return buf.getvalue()


ANALOG_META_KEYS = (
    "camera_make",
    "camera_model",
    "lens",
    "film_stock",
    "film_format",
    "shot_iso",
    "dev_process",
    "scanner",
    "photographer",
    "notes",
)


def _parse_triplet(raw, default=(0.0, 0.0, 0.0)):
    """Safely parse a 3-element float list [c, m, y] or [r, g, b]."""
    if isinstance(raw, (list, tuple)):
        vals = [float(v) for v in raw[:3]]
        while len(vals) < 3:
            vals.append(float(default[len(vals)]))
        return vals
    return list(default)


def _parse_analog_meta(data) -> dict:
    """Extract optional analog camera/film/lens/scanner technical sheet metadata."""
    raw = data.get("analog_meta") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for k in ANALOG_META_KEYS:
        val = raw.get(k)
        if val is not None:
            s = str(val).strip()
            if s:
                clean[k] = s[:240]
    return clean


def _parse_negative_params(data):
    """Extract and validate negative lab inversion parameters from JSON body."""
    printer_cmy = _parse_triplet(data.get("printer_cmy"))
    light_src = str(data.get("light_source", "standard") or "standard")
    if light_src not in LIGHT_SOURCE_MATRICES:
        light_src = "standard"
    tone_var = str(data.get("tone_variant", "standard") or "standard")
    if tone_var not in TONE_VARIANTS:
        tone_var = "standard"
    scan_src = str(data.get("scan_source", "camera_raw") or "camera_raw")
    if scan_src not in SCAN_SOURCES:
        scan_src = "camera_raw"
    color_meth = str(data.get("color_method", "dynamic") or "dynamic")
    if color_meth not in COLOR_METHODS:
        color_meth = "dynamic"
    p_finish = str(data.get("print_finish", "none") or "none")
    if p_finish not in PRINT_FINISHES:
        p_finish = "none"
    bw_toner = str(data.get("bw_toner", "neutral") or "neutral")
    if bw_toner not in BW_TONING_PROFILES:
        bw_toner = "neutral"
    sharp_mode = str(data.get("sharpen_mode", "off") or "off")
    if sharp_mode not in SHARPEN_MODES:
        sharp_mode = "off"

    raw_rb = data.get("roll_bounds")
    roll_bounds = None
    if isinstance(raw_rb, dict) and "d_min" in raw_rb and "d_max" in raw_rb:
        roll_bounds = {
            "d_min": _parse_triplet(raw_rb["d_min"]),
            "d_max": _parse_triplet(raw_rb["d_max"], default=(1.0, 1.0, 1.0)),
        }

    return {
        "base_color": data.get("base_color"),
        "film_type": data.get("film_type", "color"),
        "profile_key": _canonical_profile_key(data.get("profile", "frontier")),
        "light_source": light_src,
        "scan_source": scan_src,
        "pre_saturation": _num(data, "pre_saturation", 1.0, 0.4, 1.8),
        "color_method": color_meth,
        "roll_bounds": roll_bounds,
        "tone_variant": tone_var,
        "print_finish": p_finish,
        "finish_amount": _num(data, "finish_amount", 1.0, 0.0, 2.0),
        "bw_toner": bw_toner,
        "bw_toner_strength": _num(data, "bw_toner_strength", 1.0, 0.0, 2.0),
        "brightness": _num(data, "brightness", 0.0, -50.0, 50.0),
        "midtone_nd": _num(data, "midtone_nd", 0.0, -1.0, 1.0),
        "contrast": _num(data, "contrast", 0.0, -50.0, 50.0),
        "push_pull": _num(data, "push_pull", 0.0, -3.0, 3.0),
        "lights": _num(data, "lights", 0.0, -50.0, 50.0),
        "darks": _num(data, "darks", 0.0, -50.0, 50.0),
        "whites": _num(data, "whites", 0.0, -50.0, 50.0),
        "blacks": _num(data, "blacks", 0.0, -50.0, 50.0),
        "black_clip": _num(data, "black_clip", 0.0, -0.5, 0.5),
        "white_clip": _num(data, "white_clip", 0.0, -0.5, 0.5),
        "clip_protect": bool(data.get("clip_protect", True)),
        "inky_blacks": _num(data, "inky_blacks", 0.0, 0.0, 1.0),
        "sat_mult": _num(data, "saturation", 1.0, 0.0, 3.0),
        "rp_tone": _num(data, "rp_tone", 0.0, -0.5, 0.5),
        "border_buffer": _num(data, "border_buffer", 0.06, 0.0, 0.45),
        "crop_pct": _num(data, "crop_pct", 0.0, 0.0, 0.49),
        "glow_mult": _num(data, "glow", 1.0, 0.0, 3.0),
        "fade_mult": _num(data, "fade", 1.0, 0.0, 3.0),
        "printer_cyan_red": float(printer_cmy[0]),
        "printer_magenta_green": float(printer_cmy[1]),
        "printer_yellow_blue": float(printer_cmy[2]),
        "temp": _num(data, "temp", 0.0, -1.0, 1.0),
        "tint": _num(data, "tint", 0.0, -1.0, 1.0),
        "warming_85": _num(data, "warming_85", 0.0, 0.0, 1.0),
        "skylight_filter": _num(data, "skylight_filter", 0.0, 0.0, 1.0),
        "shade_filter": _num(data, "shade_filter", 0.0, 0.0, 1.0),
        "shadows_tint": _parse_triplet(data.get("shadows_tint")),
        "mids_tint": _parse_triplet(data.get("mids_tint")),
        "highs_tint": _parse_triplet(data.get("highs_tint")),
        "shadows_range": _num(data, "shadows_range", 0.5, 0.0, 1.0),
        "highs_range": _num(data, "highs_range", 0.5, 0.0, 1.0),
        "sharpen_mode": sharp_mode,
        "sharpen_amount": _num(data, "sharpen_amount", 1.0, 0.0, 3.0),
        "rotate": _int(data, "rotate", 0, 0, 360),
        "flip_h": bool(data.get("flip_h", False)),
    }


def _record_history_entry(pil_img, final_saved_path: Path, meta: dict):
    """Save a preview JPEG & recipe sidecar in DEVELOPED_DIR for non-destructive version history."""
    preview_name = f"{final_saved_path.stem}.jpg"
    preview_copy = DEVELOPED_DIR / preview_name
    meta_out = {
        **meta,
        "saved_path": str(final_saved_path),
        "output_format": final_saved_path.suffix.lstrip(".").upper(),
        "output_resolution": f"{pil_img.width}x{pil_img.height}",
        "developed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_path = DEVELOPED_DIR / f"{final_saved_path.stem}.meta.json"

    # Write both files through temporary siblings so an interrupted save can
    # never leave a truncated preview or a half-written sidecar behind.
    preview_tmp = preview_copy.with_name(f".{preview_copy.name}.part")
    meta_tmp = meta_path.with_name(f".{meta_path.name}.part")
    try:
        pil_img.save(preview_tmp, format="JPEG", quality=92)
        with open(meta_tmp, "w", encoding="utf-8") as f:
            json.dump(meta_out, f, indent=2, ensure_ascii=False)
        os.replace(preview_tmp, preview_copy)
        os.replace(meta_tmp, meta_path)
    except Exception:
        preview_tmp.unlink(missing_ok=True)
        meta_tmp.unlink(missing_ok=True)
        raise
    return meta_out


def _resolve_sheet_meta(valid_filenames, per_frame_recipes, app_mode, fallback_key, fallback_name):
    """Compute contact-sheet header stock label (detecting mixed rolls) and short frame stems."""
    frame_labels = [Path(fn).stem for fn in valid_filenames]
    if not valid_filenames:
        return fallback_name, frame_labels

    recipes = per_frame_recipes if isinstance(per_frame_recipes, dict) else {}
    used_keys = []
    seen = set()

    for fname in valid_filenames:
        fr = recipes.get(fname)
        if app_mode == "negative":
            raw_k = (fr.get("profile") if isinstance(fr, dict) else None) or fallback_key
            resolved_k = raw_k if raw_k in MINILAB_PROFILES else fallback_key
        else:
            raw_k = (fr.get("film") if isinstance(fr, dict) else None) or fallback_key
            resolved_k = get_film(raw_k)["key"]
        if resolved_k not in seen:
            seen.add(resolved_k)
            used_keys.append(resolved_k)

    if app_mode == "negative":
        if len(used_keys) > 1:
            return f"Negativo · Mixto ({len(used_keys)} perfiles)", frame_labels
        p_info = MINILAB_PROFILES.get(used_keys[0], MINILAB_PROFILES["frontier"])
        return f"Negativo · {p_info['name']}", frame_labels

    if len(used_keys) > 1:
        return f"Rollo mixto ({len(used_keys)} emulsiones)", frame_labels
    return get_film(used_keys[0])["name"], frame_labels


def _collect_sheet_frames(filenames, render_thumb_fn):
    """Render sheet thumbnails in parallel while preserving 1:1 (valid_filenames, images) order."""
    def _task(fname):
        img = render_thumb_fn(fname)
        return (fname, img) if img is not None else None

    max_workers = min(6, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pairs = list(executor.map(_task, filenames))
    else:
        pairs = [_task(fn) for fn in filenames]

    valid_filenames = [fn for item in pairs if item is not None for fn, _ in [item]]
    rendered_images = [img for item in pairs if item is not None for _, img in [item]]
    return valid_filenames, rendered_images


# -------------------------------------------------------------
# CORE STUDIO & FILM EMULATION ROUTES
# -------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", about=about_payload(), api_token=API_TOKEN)


@app.route("/api/about")
def api_about():
    """Return JSON manifest with application identity, authorship, and licensing."""
    return jsonify(about_payload())


@app.route("/api/check-update")
def api_check_update():
    """Check for Haluro updates with privacy, zero telemetry, and timeout safety."""
    return jsonify(check_for_updates())


@app.route("/api/open-external", methods=["POST"])
def api_open_external():
    """Safely open an approved external download URL in the host's default web browser."""
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL requerida"}), 400
    success = open_external_url(url)
    return jsonify({"ok": success, "url": url})


@app.route("/favicon.ico")
def favicon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28">'
        '<rect x="2" y="2" width="24" height="24" rx="6" fill="#1B1E23" stroke="#E59528" stroke-width="1.5"/>'
        '<circle cx="14" cy="14" r="6.5" fill="none" stroke="#ECEEF2" stroke-width="1.4"/>'
        '<polygon points="14,9.5 18,14 14,18.5 10,14" fill="#E59528"/></svg>'
    )
    return app.response_class(svg, mimetype="image/svg+xml")


@app.route("/api/health")
def api_health():
    """Health and cross-platform runtime readiness endpoint."""
    lut_files = list(LUT_DIR.rglob("*.cube")) if LUT_DIR.is_dir() else []
    return jsonify({
        "status": "ok",
        "app": APP_NAME,
        "version": __version__,
        "platform": get_platform_tag(),
        "films_count": len(list_films()),
        "luts_count": len(lut_files),
        "runtime": get_runtime_diagnostics(),
    })


@app.route("/api/films")
def api_films():
    return jsonify({"films": list_films()})


@app.route("/api/load_sample", methods=["POST"])
def api_load_sample():
    sample_file = SAMPLES_DIR / "SAMPLE.CR2"
    if not sample_file.is_file():
        return jsonify({"error": "Archivo RAW de muestra no encontrado"}), 404

    dest = UPLOAD_DIR / "SAMPLE.CR2"
    if not dest.is_file():
        import shutil
        shutil.copy(sample_file, dest)

    return jsonify({
        "filename": "SAMPLE.CR2",
        "name": "SAMPLE.CR2 (Canon RAW)",
        "is_raw": True,
        "size_bytes": dest.stat().st_size,
        "thumb_url": "/api/thumbnail/SAMPLE.CR2",
    })


def _is_readable_media(path: Path, is_raw: bool, is_heif: bool) -> bool:
    """Verify that a stored upload really contains decodable image data.

    The extension alone is not evidence: a 10-byte text file named ".jpg" was
    previously accepted, stored, and only failed later inside the engine.
    """
    try:
        if is_raw:
            import rawpy
            with rawpy.imread(str(path)) as raw:
                return int(raw.sizes.width) > 0 and int(raw.sizes.height) > 0
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        # HEIF without the optional pillow-heif backend cannot be validated here.
        return bool(is_heif)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    raw_ext = Path(f.filename).suffix.lower()
    if not raw_ext:
        return jsonify({"error": "El archivo debe incluir una extensión (.cr2, .tif, .jpg…)."}), 400
    if raw_ext not in ALLOWED_INPUT_EXTS:
        return jsonify({"error": f"Formato no compatible ({raw_ext}). Usa RAW, TIFF, JPG, PNG o HEIF."}), 400

    filename = _sanitize_filename(f.filename)
    save_path = _unique_upload_path(filename)
    stored_filename = save_path.name
    f.save(save_path)

    suffix_lower = save_path.suffix.lower()
    is_raw = suffix_lower in RAW_EXTENSIONS
    is_heif = suffix_lower in HEIF_EXTENSIONS

    if not _is_readable_media(save_path, is_raw, is_heif):
        save_path.unlink(missing_ok=True)
        return jsonify({"error": "El archivo no contiene una imagen válida o está corrupto."}), 400

    return jsonify({
        "filename": stored_filename,
        "name": Path(f.filename).name,
        "is_raw": is_raw,
        "is_heif": is_heif,
        "size_bytes": save_path.stat().st_size,
        "thumb_url": f"/api/thumbnail/{stored_filename}",
    })


@app.route("/api/thumbnail/<filename>")
def api_thumbnail(filename):
    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Miniatura no encontrada"}), 404
    jpeg_bytes = _cached_thumb_bytes(str(fpath), fpath.stat().st_mtime_ns)
    return send_file(io.BytesIO(jpeg_bytes), mimetype="image/jpeg", max_age=3600)


@app.route("/api/preview", methods=["POST"])
def api_preview():
    data = request.json or {}
    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    include_original = bool(data.get("include_original", True))

    file_path = _resolve_source_file(filename, fallback_name="SAMPLE.CR2")
    if not file_path:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    t0 = time.time()
    developed_img = develop_frame(
        file_path,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        vignette_mult=vignette,
        add_date=add_date,
        max_dim=1280,
        rotate=rotate,
        flip_h=flip_h,
    )
    render_time = round(time.time() - t0, 3)

    buf = io.BytesIO()
    developed_img.save(buf, format="JPEG", quality=89)
    dev_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    resp = {
        "developed": dev_b64,
        "render_time": render_time,
        "width": developed_img.width,
        "height": developed_img.height,
        "film": get_film(film_key),
    }
    if include_original:
        resp["original"] = _cached_original_b64(
            str(file_path), file_path.stat().st_mtime_ns, 1280, rotate, flip_h, 0
        )
    return jsonify(resp)


@app.route("/api/develop_full", methods=["POST"])
def api_develop_full():
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE.CR2"]))
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    gen_sheet = bool(data.get("sheet", True))
    out_ext = _normalize_ext(data.get("format", "jpg"))
    raw_roll_name = str(data.get("roll_name", "ROLL 001")).strip()[:40] or "ROLL 001"
    roll_name = secure_filename(raw_roll_name) or "ROLL_001"
    columns = _int(data, "columns", 4, 2, 8)

    film_info = get_film(film_key)
    out_roll_dir = DEVELOPED_DIR / f"{roll_name}_{film_key}"
    out_roll_dir.mkdir(parents=True, exist_ok=True)

    analog_meta = _parse_analog_meta(data)
    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _develop_one(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None

        fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        f_film = _canonical_film_key(fr.get("film", film_key)) if isinstance(fr, dict) else film_key
        f_ev = _num(fr, "ev", ev, -10.0, 10.0) if isinstance(fr, dict) else ev
        f_hal = _num(fr, "halation", halation, 0.0, 5.0) if isinstance(fr, dict) else halation
        f_grn = _num(fr, "grain", grain, 0.0, 5.0) if isinstance(fr, dict) else grain
        f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = _int(fr, "rotate", rotate, 0, 360) if isinstance(fr, dict) else rotate
        f_flip = bool(fr.get("flip_h", flip_h)) if isinstance(fr, dict) else flip_h

        dev_img, srgb_f = develop_frame(
            fpath,
            film_key=f_film,
            ev_adjust=f_ev,
            halation_mult=f_hal,
            grain_mult=f_grn,
            vignette_mult=f_vig,
            add_date=f_date,
            max_dim=None,
            rotate=f_rot,
            flip_h=f_flip,
            return_float=True,
        )
        out_name = f"{fpath.stem}_{f_film}{out_ext}"
        target_path = out_roll_dir / out_name
        save_output_image(
            dev_img,
            target_path,
            source_path=fpath,
            quality=96,
            float_srgb=srgb_f,
            analog_meta=analog_meta,
        )
        return (fname, out_name, dev_img)

    max_workers = min(MAX_FULL_RES_WORKERS, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_develop_one, filenames))
    else:
        results = [_develop_one(fn) for fn in filenames]

    valid_filenames = []
    developed_images = []
    output_files = []
    for res in results:
        if res:
            fn, out_name, dev_img = res
            valid_filenames.append(fn)
            output_files.append(out_name)
            developed_images.append(dev_img)

    sheet_created = False
    if gen_sheet and developed_images:
        sheet_film_name, frame_labels = _resolve_sheet_meta(
            valid_filenames, per_frame_recipes, "simulation", film_key, film_info["name"]
        )
        sheet = generate_contact_sheet(
            developed_images,
            roll_name=raw_roll_name,
            film_name=sheet_film_name,
            columns=columns,
            frame_labels=frame_labels,
        )
        sheet_path = out_roll_dir / "SHEET.jpg"
        sheet.save(sheet_path, quality=93, subsampling=0, icc_profile=get_srgb_icc_bytes())
        output_files.append("SHEET.jpg")
        sheet_created = True

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "roll_dir": str(out_roll_dir),
        "roll_folder": f"{roll_name}_{film_key}",
        "files": output_files,
        "sheet": sheet_created,
        "total_frames": len(developed_images),
        "elapsed_seconds": elapsed,
    })


@app.route("/api/contact_sheet_preview", methods=["POST"])
def api_contact_sheet_preview():
    """Ultra-fast concurrent preview of film emulation contact sheet without disk writes."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE.CR2"]))
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    raw_roll_name = str(data.get("roll_name", "PREVIEW")).strip()[:40] or "PREVIEW"
    columns = _int(data, "columns", 4, 2, 8)

    film_info = get_film(film_key)
    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _render_thumb(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None
        fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        f_film = _canonical_film_key(fr.get("film", film_key)) if isinstance(fr, dict) else film_key
        f_ev = _num(fr, "ev", ev, -10.0, 10.0) if isinstance(fr, dict) else ev
        f_hal = _num(fr, "halation", halation, 0.0, 5.0) if isinstance(fr, dict) else halation
        f_grn = _num(fr, "grain", grain, 0.0, 5.0) if isinstance(fr, dict) else grain
        f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = _int(fr, "rotate", rotate, 0, 360) if isinstance(fr, dict) else rotate
        f_flip = bool(fr.get("flip_h", flip_h)) if isinstance(fr, dict) else flip_h

        return develop_frame(
            fpath,
            film_key=f_film,
            ev_adjust=f_ev,
            halation_mult=f_hal,
            grain_mult=f_grn,
            vignette_mult=f_vig,
            add_date=f_date,
            max_dim=720,
            rotate=f_rot,
            flip_h=f_flip,
        )

    valid_filenames, rendered_images = _collect_sheet_frames(filenames, _render_thumb)

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet_film_name, frame_labels = _resolve_sheet_meta(
        valid_filenames, per_frame_recipes, "simulation", film_key, film_info["name"]
    )
    sheet, layout_boxes = generate_contact_sheet(
        rendered_images,
        roll_name=raw_roll_name,
        film_name=sheet_film_name,
        columns=columns,
        thumb_width=480,
        return_layout=True,
        frame_labels=frame_labels,
    )

    cache_dir = DEVELOPED_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # The cache file is namespaced per mode: simulation and negative sheets used
    # to share one path, so two overlapping requests served each other's image.
    _mode_tag = "simulation"
    sheet_cache_path = cache_dir / f"sheet_preview_{_mode_tag}.jpg"
    sheet.save(sheet_cache_path, format="JPEG", quality=90)

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "sheet": True,
        "sheet_url": f"/api/image/cache/{sheet_cache_path.name}?t={int(time.time() * 1000)}",
        "layout": layout_boxes,
        "total_frames": len(rendered_images),
        "width": sheet.width,
        "height": sheet.height,
        "elapsed_seconds": elapsed,
    })


@app.route("/api/save_contact_sheet", methods=["POST"])
def api_save_contact_sheet():
    """Render archival high-resolution contact sheet only and save directly or to chosen path."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE.CR2"]))
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    reveal = bool(data.get("reveal", True))
    raw_roll_name = str(data.get("roll_name", "HALURO ROLL")).strip()[:40] or "HALURO ROLL"
    roll_name = secure_filename(raw_roll_name) or "HALURO_ROLL"
    columns = _int(data, "columns", 4, 2, 8)

    dest_path = data.get("dest_path")
    if dest_path:
        target_path, err = _validate_destination_path(dest_path)
        if err:
            return jsonify({"error": err}), 400
    else:
        downloads_dir = get_downloads_dir()
        base_name = f"Haluro_Contactos_{roll_name}_{film_key}.jpg"
        target_path = downloads_dir / base_name
        counter = 1
        while target_path.exists():
            target_path = downloads_dir / f"Haluro_Contactos_{roll_name}_{film_key}_{counter}.jpg"
            counter += 1

    film_info = get_film(film_key)
    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _render_thumb(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None
        fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        f_film = _canonical_film_key(fr.get("film", film_key)) if isinstance(fr, dict) else film_key
        f_ev = _num(fr, "ev", ev, -10.0, 10.0) if isinstance(fr, dict) else ev
        f_hal = _num(fr, "halation", halation, 0.0, 5.0) if isinstance(fr, dict) else halation
        f_grn = _num(fr, "grain", grain, 0.0, 5.0) if isinstance(fr, dict) else grain
        f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = _int(fr, "rotate", rotate, 0, 360) if isinstance(fr, dict) else rotate
        f_flip = bool(fr.get("flip_h", flip_h)) if isinstance(fr, dict) else flip_h

        return develop_frame(
            fpath,
            film_key=f_film,
            ev_adjust=f_ev,
            halation_mult=f_hal,
            grain_mult=f_grn,
            vignette_mult=f_vig,
            add_date=f_date,
            max_dim=1400,
            rotate=f_rot,
            flip_h=f_flip,
        )

    valid_filenames, rendered_images = _collect_sheet_frames(filenames, _render_thumb)

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet_film_name, frame_labels = _resolve_sheet_meta(
        valid_filenames, per_frame_recipes, "simulation", film_key, film_info["name"]
    )
    sheet = generate_contact_sheet(
        rendered_images,
        roll_name=raw_roll_name,
        film_name=sheet_film_name,
        columns=columns,
        thumb_width=960,
        frame_labels=frame_labels,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target_path, format="JPEG", quality=94, subsampling=0, icc_profile=get_srgb_icc_bytes())

    if reveal:
        reveal_in_file_manager(target_path)

    _record_history_entry(sheet, target_path, {
        "type": "contact_sheet",
        "film": film_info["name"],
        "roll_name": roll_name,
        "frames_count": len(rendered_images),
    })

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "saved_path": str(target_path),
        "filename": target_path.name,
        "width": sheet.width,
        "height": sheet.height,
        "elapsed_seconds": elapsed,
    })


@app.route("/api/export_single", methods=["POST"])
def api_export_single():
    """Export single frame at FULL resolution without touching original."""
    data = request.json or {}
    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    out_ext = _normalize_ext(data.get("format", "jpg"))

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    film_info = get_film(film_key)
    out_filename = f"{fpath.stem}_{film_key}{out_ext}"
    target_path = DEVELOPED_DIR / out_filename

    analog_meta = _parse_analog_meta(data)
    t0 = time.time()
    dev_img, srgb_f = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        vignette_mult=vignette,
        add_date=add_date,
        max_dim=None,
        rotate=rotate,
        flip_h=flip_h,
        return_float=True,
    )
    save_output_image(
        dev_img,
        target_path,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
    )
    render_time = round(time.time() - t0, 2)

    meta = _record_history_entry(dev_img, target_path, {
        "mode": "simulation",
        "source_original": str(fpath.name),
        "source_original_untouched": True,
        "film_key": film_key,
        "film_name": film_info["name"],
        "ev_adjust": ev,
        "halation_mult": halation,
        "grain_mult": grain,
        "vignette_mult": vignette,
        "date_stamp": add_date,
        "rotate": rotate,
        "flip_h": flip_h,
        "analog_meta": analog_meta,
    })

    return jsonify({
        "success": True,
        "filename": out_filename,
        "path": str(target_path),
        "download_url": f"/api/download_file/{out_filename}",
        "width": dev_img.width,
        "height": dev_img.height,
        "render_time": render_time,
        "recipe_meta": meta,
    })


@app.route("/api/export_and_download")
def api_export_and_download():
    """Stream full-resolution developed image directly as a download attachment."""
    filename = request.args.get("filename", "SAMPLE.CR2")
    film_key = request.args.get("film", "portra400")
    ev = float(request.args.get("ev", 0.0))
    halation = float(request.args.get("halation", 1.0))
    grain = float(request.args.get("grain", 1.0))
    vignette = float(request.args.get("vignette", 1.0))
    add_date = request.args.get("date", "false").lower() == "true"

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    dev_img = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        vignette_mult=vignette,
        add_date=add_date,
        max_dim=None,
    )

    buf = io.BytesIO()
    dev_img.save(buf, format="JPEG", quality=96, subsampling=0)
    buf.seek(0)

    download_name = f"{fpath.stem}_{film_key}.jpg"
    return send_file(buf, mimetype="image/jpeg", as_attachment=True, download_name=download_name)


@app.route("/api/save_direct_to_downloads", methods=["POST"])
def api_save_direct_to_downloads():
    """Save full-res developed photo directly to ~/Downloads and optionally reveal in Finder."""
    data = request.json or {}
    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    out_ext = _normalize_ext(data.get("format", "jpg"))
    reveal = bool(data.get("reveal", True))

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    film_info = get_film(film_key)
    downloads_dir = get_downloads_dir()

    stem_base = f"{fpath.stem}_{film_key}"
    target_path = downloads_dir / f"{stem_base}{out_ext}"
    counter = 1
    while target_path.exists():
        target_path = downloads_dir / f"{stem_base}_{counter}{out_ext}"
        counter += 1

    analog_meta = _parse_analog_meta(data)
    t0 = time.time()
    dev_img, srgb_f = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        vignette_mult=vignette,
        add_date=add_date,
        max_dim=None,
        rotate=rotate,
        flip_h=flip_h,
        return_float=True,
    )
    save_output_image(
        dev_img,
        target_path,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
    )

    _record_history_entry(dev_img, target_path, {
        "mode": "simulation",
        "source_original": str(fpath.name),
        "source_original_untouched": True,
        "film_key": film_key,
        "film_name": film_info["name"],
        "ev_adjust": ev,
        "halation_mult": halation,
        "grain_mult": grain,
        "vignette_mult": vignette,
        "date_stamp": add_date,
        "rotate": rotate,
        "flip_h": flip_h,
        "analog_meta": analog_meta,
    })

    if reveal:
        reveal_in_file_manager(target_path)

    return jsonify({
        "success": True,
        "saved_path": str(target_path),
        "filename": target_path.name,
        "width": dev_img.width,
        "height": dev_img.height,
        "render_time": round(time.time() - t0, 2),
        "revealed": reveal,
    })


@app.route("/api/choose_save_path", methods=["POST"])
def api_choose_save_path():
    """Open native Save File dialog (macOS Cocoa / Windows 11 Win32) and return chosen path."""
    data = request.json or {}
    raw_default = Path(data.get("default_name", "revelado_haluro.jpg")).name
    chosen = choose_save_path_dialog(raw_default)
    if not chosen:
        return jsonify({"cancelled": True})
    return jsonify({"chosen_path": chosen, "cancelled": False})


@app.route("/api/native_save_dialog", methods=["POST"])
def api_native_save_dialog():
    """Backward-compatible native save dialog for simulation mode across macOS and Windows 11."""
    data = request.json or {}
    if "default_name" in data and "film" not in data:
        return api_choose_save_path()

    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    out_ext = _normalize_ext(data.get("format", "jpg"))

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    default_name = f"{fpath.stem}_{film_key}{out_ext}"
    chosen = choose_save_path_dialog(default_name)
    if not chosen:
        return jsonify({"cancelled": True})

    data_with_dest = {**data, "dest_path": chosen}
    return _save_simulation_to_dest(data_with_dest, reveal=True)


def _save_simulation_to_dest(data, reveal=False):
    dest_path = data.get("dest_path")
    dest, err = _validate_destination_path(dest_path)
    if err:
        return jsonify({"error": err}), 400
    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    add_date = bool(data.get("date", False))
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    film_info = get_film(film_key)
    analog_meta = _parse_analog_meta(data)
    t0 = time.time()
    dev_img, srgb_f = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        vignette_mult=vignette,
        add_date=add_date,
        max_dim=None,
        rotate=rotate,
        flip_h=flip_h,
        return_float=True,
    )
    # Use the *validated* destination. Re-deriving it from the raw payload
    # discarded the expanduser()/resolve() normalisation and wrote to a literal
    # "~" directory inside the working folder.
    save_output_image(
        dev_img,
        dest,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
    )

    _record_history_entry(dev_img, dest, {
        "mode": "simulation",
        "source_original": str(fpath.name),
        "source_original_untouched": True,
        "film_key": film_key,
        "film_name": film_info["name"],
        "ev_adjust": ev,
        "halation_mult": halation,
        "grain_mult": grain,
        "vignette_mult": vignette,
        "date_stamp": add_date,
        "rotate": rotate,
        "flip_h": flip_h,
        "analog_meta": analog_meta,
    })

    if reveal:
        reveal_in_file_manager(dest)

    return jsonify({
        "success": True,
        "saved_path": str(dest),
        "filename": dest.name,
        "width": dev_img.width,
        "height": dev_img.height,
        "render_time": round(time.time() - t0, 2),
    })


@app.route("/api/save_to_path", methods=["POST"])
def api_save_to_path():
    return _save_simulation_to_dest(request.json or {}, reveal=False)


@app.route("/api/save_zip_to_downloads", methods=["POST"])
def api_save_zip_to_downloads():
    """Build and save full roll ZIP directly to ~/Downloads and reveal in Finder."""
    data = request.json or {}
    roll_folder = secure_filename(data.get("roll_folder") or "")
    if not roll_folder:
        return jsonify({"error": "Carpeta de rollo inválida"}), 400

    src_folder = (DEVELOPED_DIR / roll_folder).resolve()
    if not _is_within(src_folder, DEVELOPED_DIR) or not src_folder.is_dir():
        return jsonify({"error": "Carpeta de rollo no encontrada"}), 404

    downloads_dir = get_downloads_dir()
    dest_zip = downloads_dir / f"{roll_folder}.zip"

    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zip_f:
        for file_p in src_folder.iterdir():
            if file_p.is_file() and not file_p.name.startswith("."):
                zip_f.write(file_p, arcname=file_p.name)

    reveal_in_file_manager(dest_zip)
    return jsonify({
        "success": True,
        "saved_path": str(dest_zip),
        "filename": dest_zip.name,
    })


@app.route("/api/history")
def api_history():
    """List all previously developed versions with full recipe metadata."""
    history = []
    for item in sorted(DEVELOPED_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
        if item.name.startswith("SHEET"):
            continue
        meta_file = DEVELOPED_DIR / f"{item.stem}.meta.json"
        meta = {}
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Historial: metadatos ilegibles en %s (%s)", meta_file.name, exc)

        saved_target = meta.get("saved_path") or str(item)
        history.append({
            "filename": Path(saved_target).name if meta.get("saved_path") else item.name,
            "path": saved_target if Path(saved_target).exists() else str(item),
            "url": f"/api/image/{item.name}",
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.stat().st_mtime)),
            "size_bytes": item.stat().st_size,
            "meta": meta,
        })
    return jsonify({"history": history})


@app.route("/api/reveal_in_finder", methods=["POST"])
def api_reveal_in_finder():
    data = request.json or {}
    path = data.get("path")
    target = Path(path) if (path and Path(path).exists()) else DEVELOPED_DIR
    reveal_in_file_manager(target)
    return jsonify({"success": True, "revealed": str(target)})


# -------------------------------------------------------------
# NEGATIVE LAB (Optical Density Inversion & Scanner Engine)
# -------------------------------------------------------------

@app.route("/api/negative/profiles")
def api_negative_profiles():
    return jsonify({
        "profiles": list_negative_profiles(),
        "print_finishes": list_print_finishes(),
        "bw_toners": list_bw_toners(),
        "scan_sources": [{"key": k, "name": str(v["name"])} for k, v in SCAN_SOURCES.items()],
    })


@app.route("/api/negative/analyze_roll", methods=["POST"])
def api_negative_analyze_roll():
    """Analyze unified D-min film base and optical density bounds across an entire imported roll."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames") or ["SAMPLE_NEGATIVE.jpg"])
    per_frame_recipes = data.get("per_frame_recipes") or {}
    params = _parse_negative_params(data)

    linear_frames = []
    analyzed_names = []
    for fname in filenames[:72]:
        fpath = _resolve_source_file(
            fname,
            fallback_name="SAMPLE_NEGATIVE.jpg" if len(filenames) == 1 else None,
        )
        if not fpath:
            continue
        fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        rot = _int(fr, "rotate", params["rotate"], 0, 360) if isinstance(fr, dict) else params["rotate"]
        flp = bool(fr.get("flip_h", params["flip_h"])) if isinstance(fr, dict) else params["flip_h"]
        lin = load_image_linear(fpath, max_dim=640, rotate=rot, flip_h=flp)
        linear_frames.append(lin)
        analyzed_names.append(fpath.name)

    if not linear_frames:
        return jsonify({"error": "No se encontraron fotogramas válidos para analizar el rollo"}), 404

    cal = analyze_roll_calibration(
        linear_frames,
        film_type=params["film_type"],
        light_source=params["light_source"],
        scan_source=params["scan_source"],
        pre_saturation=params["pre_saturation"],
        border_buffer=params["border_buffer"],
    )
    return jsonify({
        **cal,
        "roll_bounds": {
            "d_min": cal["roll_d_min"],
            "d_max": cal["roll_d_max"],
        },
        "analyzed_files": analyzed_names,
    })


@app.route("/api/negative/load_sample", methods=["POST"])
def api_negative_load_sample():
    sample_file = SAMPLES_DIR / "SAMPLE_NEGATIVE.jpg"
    if not sample_file.is_file():
        return jsonify({"error": "Negativo de muestra no encontrado"}), 404

    # Use a dedicated, unmistakable name. The previous implementation reused
    # "SAMPLE_NEGATIVE.jpg", so a photograph the user had uploaded under that
    # name was silently returned as the sample (and could be overwritten by an
    # app update).
    sample_name = "__haluro_sample_negative__.jpg"
    dest = UPLOAD_DIR / sample_name
    if not dest.is_file() or sample_file.stat().st_mtime > dest.stat().st_mtime:
        import shutil
        shutil.copy2(sample_file, dest)

    return jsonify({
        "filename": sample_name,
        "name": "Kodak Gold 200 (Escaneo C-41)",
        "is_raw": False,
        "size_bytes": dest.stat().st_size,
        "thumb_url": f"/api/thumbnail/{sample_name}",
    })


@app.route("/api/negative/auto_detect_base", methods=["POST"])
def api_negative_auto_detect_base():
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    lin = load_image_linear(fpath, max_dim=800, rotate=rotate, flip_h=flip_h)
    base_color = auto_detect_film_base(lin)
    hex_str = linear_rgb_to_hex(base_color)
    return jsonify({
        "base_color": base_color,
        "base_hex": hex_str,
        "hex": hex_str,
    })


@app.route("/api/negative/sample_point", methods=["POST"])
def api_negative_sample_point():
    """Sample the exact film base mask from an (x_pct, y_pct) click."""
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    x_pct = _num(data, "x_pct", 0.5, 0.0, 1.0)
    y_pct = _num(data, "y_pct", 0.5, 0.0, 1.0)
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    lin = load_image_linear(fpath, max_dim=1280, rotate=rotate, flip_h=flip_h)
    h, w = lin.shape[:2]
    px = int(np.clip(x_pct * w, 0, w - 1))
    py = int(np.clip(y_pct * h, 0, h - 1))

    y0, y1 = max(0, py - 3), min(h, py + 4)
    x0, x1 = max(0, px - 3), min(w, px + 4)
    sample_box = lin[y0:y1, x0:x1]
    base_color = np.median(sample_box, axis=(0, 1)).tolist()
    hex_str = linear_rgb_to_hex(base_color)

    return jsonify({
        "base_color": base_color,
        "sampled_rgb": base_color,
        "sampled_at": [px, py],
        "base_hex": hex_str,
        "hex": hex_str,
    })


@app.route("/api/negative/sample_neutral_wb", methods=["POST"])
def api_negative_sample_neutral_wb():
    """Solve CMY printer lights to neutralize a sampled gray/shadow point directly on the positive preview."""
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    x_pct = _num(data, "x_pct", 0.5, 0.0, 1.0)
    y_pct = _num(data, "y_pct", 0.5, 0.0, 1.0)

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    params = _parse_negative_params(data)
    lin = load_image_linear(fpath, max_dim=1280, rotate=params["rotate"], flip_h=params["flip_h"])
    cmy = compute_neutral_wb_from_point(
        lin,
        x_pct=x_pct,
        y_pct=y_pct,
        base_color=params["base_color"],
        film_type=params["film_type"],
        profile_key=params["profile_key"],
        light_source=params["light_source"],
        scan_source=params["scan_source"],
        pre_saturation=params["pre_saturation"],
        color_method=params["color_method"],
        roll_bounds=params["roll_bounds"],
        border_buffer=params["border_buffer"],
        crop_pct=params["crop_pct"],
        temp=params["temp"],
        tint=params["tint"],
    )
    return jsonify({
        "printer_cmy": cmy,
        "sampled_at_pct": [round(x_pct, 4), round(y_pct, 4)],
    })


@app.route("/api/negative/auto_scene_wb", methods=["POST"])
def api_negative_auto_scene_wb():
    """Automatically compute balanced CMY printer lights for borderless camera/minilab scans."""
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    params = _parse_negative_params(data)
    lin = load_image_linear(fpath, max_dim=960, rotate=params["rotate"], flip_h=params["flip_h"])
    cmy = auto_balance_scene_wb(
        lin,
        base_color=params["base_color"],
        film_type=params["film_type"],
        profile_key=params["profile_key"],
        light_source=params["light_source"],
        scan_source=params["scan_source"],
        pre_saturation=params["pre_saturation"],
        color_method=params["color_method"],
        roll_bounds=params["roll_bounds"],
        border_buffer=params["border_buffer"],
        crop_pct=params["crop_pct"],
    )
    return jsonify({"printer_cmy": cmy})


@app.route("/api/negative/preview", methods=["POST"])
def api_negative_preview():
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    include_original = bool(data.get("include_original", True))

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    params = _parse_negative_params(data)
    t0 = time.time()
    pos_img = process_negative_to_image(fpath, max_dim=1280, **params)
    render_time = round(time.time() - t0, 3)

    buf_pos = io.BytesIO()
    pos_img.save(buf_pos, format="JPEG", quality=89)
    pos_b64 = "data:image/jpeg;base64," + base64.b64encode(buf_pos.getvalue()).decode("utf-8")

    profile_key = params["profile_key"]
    profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])

    resp = {
        "developed": pos_b64,
        "render_time": render_time,
        "width": pos_img.width,
        "height": pos_img.height,
        "profile": profile_info,
    }
    if include_original:
        crop_milli = 0 if bool(data.get("original_uncropped", False)) else int(round(params["crop_pct"] * 1000))
        resp["original"] = _cached_original_b64(
            str(fpath), fpath.stat().st_mtime_ns, 1280, params["rotate"], params["flip_h"], crop_milli
        )
    return jsonify(resp)


def _export_negative_common(data, target_path: Path, reveal: bool = False):
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    params = _parse_negative_params(data)
    analog_meta = _parse_analog_meta(data)
    profile_key = params["profile_key"]
    profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])

    t0 = time.time()
    pos_img, srgb_f = process_negative_to_image(fpath, max_dim=None, return_float=True, **params)
    save_output_image(
        pos_img,
        target_path,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
    )

    _record_history_entry(pos_img, target_path, {
        "mode": "negative_inversion",
        "source_original": str(fpath.name),
        "source_original_untouched": True,
        "profile_key": profile_key,
        "profile_name": profile_info["name"],
        "film_type": params["film_type"],
        "light_source": params["light_source"],
        "scan_source": params["scan_source"],
        "pre_saturation": params["pre_saturation"],
        "color_method": params["color_method"],
        "roll_bounds": params["roll_bounds"],
        "tone_variant": params["tone_variant"],
        "print_finish": params["print_finish"],
        "finish_amount": params["finish_amount"],
        "bw_toner": params["bw_toner"],
        "bw_toner_strength": params["bw_toner_strength"],
        "base_color": params["base_color"],
        "brightness": params["brightness"],
        "midtone_nd": params["midtone_nd"],
        "contrast": params["contrast"],
        "push_pull": params["push_pull"],
        "lights": params["lights"],
        "darks": params["darks"],
        "whites": params["whites"],
        "blacks": params["blacks"],
        "black_clip": params["black_clip"],
        "white_clip": params["white_clip"],
        "clip_protect": params["clip_protect"],
        "inky_blacks": params["inky_blacks"],
        "saturation": params["sat_mult"],
        "rp_tone": params["rp_tone"],
        "border_buffer": params["border_buffer"],
        "crop_pct": params["crop_pct"],
        "glow": params["glow_mult"],
        "fade": params["fade_mult"],
        "printer_cmy": [
            params["printer_cyan_red"],
            params["printer_magenta_green"],
            params["printer_yellow_blue"],
        ],
        "shadows_tint": params["shadows_tint"],
        "mids_tint": params["mids_tint"],
        "highs_tint": params["highs_tint"],
        "shadows_range": params["shadows_range"],
        "highs_range": params["highs_range"],
        "temp": params["temp"],
        "tint": params["tint"],
        "warming_85": params["warming_85"],
        "skylight_filter": params["skylight_filter"],
        "shade_filter": params["shade_filter"],
        "sharpen_mode": params["sharpen_mode"],
        "sharpen_amount": params["sharpen_amount"],
        "rotate": params["rotate"],
        "flip_h": params["flip_h"],
        "analog_meta": analog_meta,
    })

    if reveal:
        reveal_in_file_manager(target_path)

    return jsonify({
        "success": True,
        "saved_path": str(target_path),
        "filename": target_path.name,
        "width": pos_img.width,
        "height": pos_img.height,
        "render_time": round(time.time() - t0, 2),
        "analog_caption": format_analog_caption(analog_meta),
    })


@app.route("/api/negative/save_to_downloads", methods=["POST"])
def api_negative_save_to_downloads():
    """Save full-resolution inverted negative directly to ~/Downloads and reveal in file manager."""
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    profile_key = _canonical_profile_key(data.get("profile", "frontier"))
    out_ext = _normalize_ext(data.get("format", "jpg"))
    reveal = bool(data.get("reveal", True))

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    downloads_dir = get_downloads_dir()

    stem_base = f"{fpath.stem}_positive_{profile_key}"
    target_path = downloads_dir / f"{stem_base}{out_ext}"
    counter = 1
    while target_path.exists():
        target_path = downloads_dir / f"{stem_base}_{counter}{out_ext}"
        counter += 1

    return _export_negative_common(data, target_path, reveal=reveal)


@app.route("/api/negative/save_to_path", methods=["POST"])
def api_negative_save_to_path():
    """Save full-resolution inverted negative to a user-specified path."""
    data = request.json or {}
    dest_path = data.get("dest_path")
    dest, err = _validate_destination_path(dest_path)
    if err:
        return jsonify({"error": err}), 400
    return _export_negative_common(data, dest, reveal=False)


@app.route("/api/negative/develop_full", methods=["POST"])
def api_negative_develop_full():
    """Batch-invert an entire roll of scanned negatives and generate a positive contact sheet."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE_NEGATIVE.jpg"]))
    gen_sheet = bool(data.get("sheet", True))
    out_ext = _normalize_ext(data.get("format", "jpg"))
    raw_roll_name = str(data.get("roll_name", "NEG ROLL 001")).strip()[:40] or "NEG ROLL 001"
    roll_name = secure_filename(raw_roll_name) or "NEG_ROLL_001"
    columns = _int(data, "columns", 4, 2, 8)

    params = _parse_negative_params(data)
    analog_meta = _parse_analog_meta(data)
    profile_key = params["profile_key"]
    profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])

    out_roll_dir = DEVELOPED_DIR / f"{roll_name}_neg_{profile_key}"
    out_roll_dir.mkdir(parents=True, exist_ok=True)

    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _develop_one(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None

        fr_raw = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        if isinstance(fr_raw, dict):
            frame_params = _parse_negative_params({**data, **fr_raw})
        else:
            frame_params = params

        f_prof_key = _canonical_profile_key(frame_params["profile_key"])
        pos_img, srgb_f = process_negative_to_image(fpath, max_dim=None, return_float=True, **frame_params)
        out_name = f"{fpath.stem}_positive_{f_prof_key}{out_ext}"
        target_path = out_roll_dir / out_name
        save_output_image(
            pos_img,
            target_path,
            source_path=fpath,
            quality=96,
            float_srgb=srgb_f,
            analog_meta=analog_meta,
        )
        return (fname, out_name, pos_img)

    max_workers = min(MAX_FULL_RES_WORKERS, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_develop_one, filenames))
    else:
        results = [_develop_one(fn) for fn in filenames]

    valid_filenames = []
    developed_images = []
    output_files = []
    for res in results:
        if res:
            fn, out_name, pos_img = res
            valid_filenames.append(fn)
            output_files.append(out_name)
            developed_images.append(pos_img)

    sheet_created = False
    if gen_sheet and developed_images:
        sheet_film_name, frame_labels = _resolve_sheet_meta(
            valid_filenames, per_frame_recipes, "negative", profile_key, f"Negativo · {profile_info['name']}"
        )
        sheet = generate_contact_sheet(
            developed_images,
            roll_name=raw_roll_name,
            film_name=sheet_film_name,
            columns=columns,
            frame_labels=frame_labels,
        )
        sheet_path = out_roll_dir / "SHEET.jpg"
        sheet.save(sheet_path, quality=93, subsampling=0, icc_profile=get_srgb_icc_bytes())
        output_files.append("SHEET.jpg")
        sheet_created = True

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "roll_dir": str(out_roll_dir),
        "roll_folder": f"{roll_name}_neg_{profile_key}",
        "files": output_files,
        "sheet": sheet_created,
        "total_frames": len(developed_images),
        "elapsed_seconds": elapsed,
    })


@app.route("/api/negative/contact_sheet_preview", methods=["POST"])
def api_negative_contact_sheet_preview():
    """Ultra-fast concurrent preview of negative inversion contact sheet without disk writes."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE_NEGATIVE.jpg"]))
    raw_roll_name = str(data.get("roll_name", "PREVIEW NEG")).strip()[:40] or "PREVIEW NEG"
    columns = _int(data, "columns", 4, 2, 8)

    params = _parse_negative_params(data)
    profile_key = params["profile_key"]
    profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])

    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _render_thumb(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None
        fr_raw = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        if isinstance(fr_raw, dict):
            frame_params = _parse_negative_params({**data, **fr_raw})
        else:
            frame_params = params

        return process_negative_to_image(fpath, max_dim=720, return_float=False, **frame_params)

    valid_filenames, rendered_images = _collect_sheet_frames(filenames, _render_thumb)

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet_film_name, frame_labels = _resolve_sheet_meta(
        valid_filenames, per_frame_recipes, "negative", profile_key, f"Negativo · {profile_info['name']}"
    )
    sheet, layout_boxes = generate_contact_sheet(
        rendered_images,
        roll_name=raw_roll_name,
        film_name=sheet_film_name,
        columns=columns,
        thumb_width=480,
        return_layout=True,
        frame_labels=frame_labels,
    )

    cache_dir = DEVELOPED_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _mode_tag = "negative"
    sheet_cache_path = cache_dir / f"sheet_preview_{_mode_tag}.jpg"
    sheet.save(sheet_cache_path, format="JPEG", quality=90)

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "sheet": True,
        "sheet_url": f"/api/image/cache/{sheet_cache_path.name}?t={int(time.time() * 1000)}",
        "layout": layout_boxes,
        "total_frames": len(rendered_images),
        "width": sheet.width,
        "height": sheet.height,
        "elapsed_seconds": elapsed,
    })


@app.route("/api/negative/save_contact_sheet", methods=["POST"])
def api_negative_save_contact_sheet():
    """Render archival high-resolution negative contact sheet only and save directly or to chosen path."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE_NEGATIVE.jpg"]))
    raw_roll_name = str(data.get("roll_name", "HALURO NEG")).strip()[:40] or "HALURO NEG"
    roll_name = secure_filename(raw_roll_name) or "HALURO_NEG"
    columns = _int(data, "columns", 4, 2, 8)
    reveal = bool(data.get("reveal", True))

    params = _parse_negative_params(data)
    profile_key = params["profile_key"]
    profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])

    dest_path = data.get("dest_path")
    if dest_path:
        target_path, err = _validate_destination_path(dest_path)
        if err:
            return jsonify({"error": err}), 400
    else:
        downloads_dir = get_downloads_dir()
        base_name = f"Haluro_Contactos_{roll_name}_{profile_key}.jpg"
        target_path = downloads_dir / base_name
        counter = 1
        while target_path.exists():
            target_path = downloads_dir / f"Haluro_Contactos_{roll_name}_{profile_key}_{counter}.jpg"
            counter += 1

    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _render_thumb(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None
        fr_raw = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        if isinstance(fr_raw, dict):
            frame_params = _parse_negative_params({**data, **fr_raw})
        else:
            frame_params = params

        return process_negative_to_image(fpath, max_dim=1400, return_float=False, **frame_params)

    valid_filenames, rendered_images = _collect_sheet_frames(filenames, _render_thumb)

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet_film_name, frame_labels = _resolve_sheet_meta(
        valid_filenames, per_frame_recipes, "negative", profile_key, f"Negativo · {profile_info['name']}"
    )
    sheet = generate_contact_sheet(
        rendered_images,
        roll_name=raw_roll_name,
        film_name=sheet_film_name,
        columns=columns,
        thumb_width=960,
        frame_labels=frame_labels,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target_path, format="JPEG", quality=94, subsampling=0, icc_profile=get_srgb_icc_bytes())

    if reveal:
        reveal_in_file_manager(target_path)

    _record_history_entry(sheet, target_path, {
        "type": "contact_sheet",
        "film": f"Negativo · {profile_info['name']}",
        "roll_name": roll_name,
        "frames_count": len(rendered_images),
    })

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "saved_path": str(target_path),
        "filename": target_path.name,
        "width": sheet.width,
        "height": sheet.height,
        "elapsed_seconds": elapsed,
    })


# -------------------------------------------------------------
# ASYNC BATCH ROLL PROGRESS & CANCELLATION ENDPOINTS
# -------------------------------------------------------------

_batch_jobs_lock = threading.Lock()
_batch_jobs = {}


def _update_batch_job(job_id, **kwargs):
    with _batch_jobs_lock:
        if job_id in _batch_jobs:
            _batch_jobs[job_id].update(kwargs)


def _run_batch_roll_worker(job_id, data):
    job = _batch_jobs[job_id]
    cancel_event = job["cancel_event"]
    t_start = time.time()

    try:
        app_mode = data.get("app_mode", "simulation")
        filenames = _bounded_frames(data.get("filenames", []))
        gen_sheet = bool(data.get("sheet", True))
        out_ext = _normalize_ext(data.get("format", "jpg"))
        raw_roll_name = str(data.get("roll_name", "HALURO ROLL")).strip()[:40] or "HALURO ROLL"
        roll_name = secure_filename(raw_roll_name) or "HALURO_ROLL"
        columns = _int(data, "columns", 4, 2, 8)
        analog_meta = _parse_analog_meta(data)
        per_frame_recipes = data.get("per_frame_recipes") or {}

        is_neg = app_mode == "negative"
        if is_neg:
            params = _parse_negative_params(data)
            profile_key = params["profile_key"]
            profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])
            roll_folder = f"{roll_name}_neg_{profile_key}"
            sheet_film_name = f"Negativo · {profile_info['name']}"
        else:
            film_key = _canonical_film_key(data.get("film", "portra400"))
            ev = _num(data, "ev", 0.0, -10.0, 10.0)
            halation = _num(data, "halation", 1.0, 0.0, 5.0)
            grain = _num(data, "grain", 1.0, 0.0, 5.0)
            vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
            add_date = bool(data.get("date", False))
            rotate = _int(data, "rotate", 0, 0, 360)
            flip_h = bool(data.get("flip_h", False))
            film_info = get_film(film_key)
            roll_folder = f"{roll_name}_{film_key}"
            sheet_film_name = film_info["name"]

        out_roll_dir = DEVELOPED_DIR / roll_folder
        out_roll_dir.mkdir(parents=True, exist_ok=True)

        total = len(filenames)
        indexed_results = {}
        completed_count = 0
        progress_lock = threading.Lock()

        def _worker_task(idx_and_name):
            idx, fname = idx_and_name
            if cancel_event.is_set():
                return None

            fpath = _resolve_source_file(fname)
            if not fpath:
                return None

            if is_neg:
                fr_raw = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
                frame_params = _parse_negative_params({**data, **fr_raw}) if isinstance(fr_raw, dict) else params
                f_prof_key = _canonical_profile_key(frame_params["profile_key"])
                img, srgb_f = process_negative_to_image(fpath, max_dim=None, return_float=True, **frame_params)
                out_name = f"{fpath.stem}_positive_{f_prof_key}{out_ext}"
            else:
                fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
                f_film = _canonical_film_key(fr.get("film", film_key)) if isinstance(fr, dict) else film_key
                f_ev = _num(fr, "ev", ev, -10.0, 10.0) if isinstance(fr, dict) else ev
                f_hal = _num(fr, "halation", halation, 0.0, 5.0) if isinstance(fr, dict) else halation
                f_grn = _num(fr, "grain", grain, 0.0, 5.0) if isinstance(fr, dict) else grain
                f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
                f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
                f_rot = _int(fr, "rotate", rotate, 0, 360) if isinstance(fr, dict) else rotate
                f_flip = bool(fr.get("flip_h", flip_h)) if isinstance(fr, dict) else flip_h
                img, srgb_f = develop_frame(
                    fpath,
                    film_key=f_film,
                    ev_adjust=f_ev,
                    halation_mult=f_hal,
                    grain_mult=f_grn,
                    vignette_mult=f_vig,
                    add_date=f_date,
                    max_dim=None,
                    rotate=f_rot,
                    flip_h=f_flip,
                    return_float=True,
                )
                out_name = f"{fpath.stem}_{f_film}{out_ext}"

            if cancel_event.is_set():
                return None

            target_path = out_roll_dir / out_name
            save_output_image(
                img,
                target_path,
                source_path=fpath,
                quality=96,
                float_srgb=srgb_f,
                analog_meta=analog_meta,
            )
            return (idx, fpath.name, out_name, img)

        max_workers = min(MAX_FULL_RES_WORKERS, max(1, os.cpu_count() or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_worker_task, (i, fn)) for i, fn in enumerate(filenames)]
            for fut in as_completed(futures):
                if cancel_event.is_set():
                    for pending_f in futures:
                        pending_f.cancel()
                    _update_batch_job(
                        job_id,
                        status="cancelled",
                        current_file="Proceso cancelado por el usuario.",
                        elapsed_seconds=round(time.time() - t_start, 1),
                    )
                    return

                res = fut.result()
                if res:
                    idx, src_name, out_name, img = res
                    indexed_results[idx] = (out_name, img)
                    with progress_lock:
                        completed_count += 1
                        pct = int(round((completed_count / max(1, total)) * 90))
                        _update_batch_job(
                            job_id,
                            completed=completed_count,
                            percent=pct,
                            current_file=src_name,
                            elapsed_seconds=round(time.time() - t_start, 1),
                        )

        if cancel_event.is_set():
            _update_batch_job(
                job_id,
                status="cancelled",
                current_file="Proceso cancelado por el usuario.",
                elapsed_seconds=round(time.time() - t_start, 1),
            )
            return

        valid_filenames = []
        developed_images = []
        output_files = []
        for idx in sorted(indexed_results.keys()):
            out_name, img = indexed_results[idx]
            valid_filenames.append(filenames[idx])
            output_files.append(out_name)
            developed_images.append(img)

        sheet_created = False
        if gen_sheet and developed_images:
            _update_batch_job(
                job_id,
                percent=94,
                current_file="Componiendo hoja de contactos de archivo…",
                elapsed_seconds=round(time.time() - t_start, 1),
            )
            batch_sheet_film, frame_labels = _resolve_sheet_meta(
                valid_filenames,
                per_frame_recipes,
                app_mode,
                profile_key if is_neg else film_key,
                sheet_film_name,
            )
            sheet = generate_contact_sheet(
                developed_images,
                roll_name=raw_roll_name,
                film_name=batch_sheet_film,
                columns=columns,
                frame_labels=frame_labels,
            )
            sheet_path = out_roll_dir / "SHEET.jpg"
            sheet.save(sheet_path, quality=93, subsampling=0, icc_profile=get_srgb_icc_bytes())
            output_files.append("SHEET.jpg")
            sheet_created = True

        elapsed = round(time.time() - t_start, 2)
        _update_batch_job(
            job_id,
            status="completed",
            completed=len(developed_images),
            percent=100,
            current_file="¡Rollo completado!",
            elapsed_seconds=elapsed,
            result={
                "success": True,
                "roll_dir": str(out_roll_dir),
                "roll_folder": roll_folder,
                "files": output_files,
                "sheet": sheet_created,
                "total_frames": len(developed_images),
                "elapsed_seconds": elapsed,
            },
        )
    except Exception as exc:
        logger.exception("Batch roll job failed: %s", exc)
        _update_batch_job(
            job_id,
            status="error",
            error=str(exc),
            elapsed_seconds=round(time.time() - t_start, 1),
        )


@app.route("/api/batch/develop_roll_start", methods=["POST"])
def api_batch_develop_roll_start():
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", []))
    if not filenames:
        return jsonify({"error": "No hay fotogramas para procesar"}), 400

    job_id = str(uuid.uuid4())[:10]
    with _batch_jobs_lock:
        if len(_batch_jobs) > 20:
            oldest = list(_batch_jobs.keys())[:-10]
            for k in oldest:
                _batch_jobs.pop(k, None)
        _batch_jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "total": len(filenames),
            "completed": 0,
            "percent": 2,
            "current_file": "Preparando cámara oscura…",
            "elapsed_seconds": 0.0,
            "result": None,
            "error": None,
            "cancel_event": threading.Event(),
        }

    t = threading.Thread(target=_run_batch_roll_worker, args=(job_id, data), daemon=True)
    t.start()
    return jsonify({"success": True, "job_id": job_id, "total": len(filenames)})


@app.route("/api/batch/develop_status/<job_id>", methods=["GET"])
def api_batch_develop_status(job_id):
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return jsonify({"status": "not_found", "error": "Trabajo no encontrado"}), 404
        payload = {k: v for k, v in job.items() if k != "cancel_event"}
    return jsonify(payload)


@app.route("/api/batch/develop_cancel/<job_id>", methods=["POST"])
def api_batch_develop_cancel(job_id):
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "error": "Trabajo no encontrado"}), 404
        job["cancel_event"].set()
        if job["status"] == "running":
            job["status"] = "cancelling"
            job["current_file"] = "Deteniendo hilos de procesamiento…"
    return jsonify({"success": True})


# -------------------------------------------------------------
# FILE & STATIC DELIVERY ROUTES
# -------------------------------------------------------------

@app.route("/api/open_folder", methods=["POST"])
def api_open_folder():
    open_directory(DEVELOPED_DIR)
    return jsonify({"success": True, "path": str(DEVELOPED_DIR)})


@app.route("/api/download_file/<filename>")
def api_download_file(filename):
    safe_name = Path(filename).name
    cand = (DEVELOPED_DIR / safe_name).resolve()
    if not _is_within(cand, DEVELOPED_DIR) or not cand.is_file():
        return jsonify({"error": "Archivo no encontrado"}), 404
    return send_from_directory(DEVELOPED_DIR, safe_name, as_attachment=True)


@app.route("/api/download_roll/<roll_folder>")
def api_download_roll(roll_folder):
    safe_roll = secure_filename(roll_folder)
    folder_path = (DEVELOPED_DIR / safe_roll).resolve()
    if not _is_within(folder_path, DEVELOPED_DIR) or not folder_path.is_dir():
        return jsonify({"error": "Carpeta de rollo no encontrada"}), 404

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_p in folder_path.iterdir():
            if file_p.is_file() and not file_p.name.startswith("."):
                zip_file.write(file_p, arcname=file_p.name)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_roll}.zip",
    )


@app.route("/api/image/<path:subpath>")
def api_serve_image(subpath):
    cand = (DEVELOPED_DIR / subpath).resolve()
    if not _is_within(cand, DEVELOPED_DIR) or not cand.is_file():
        return jsonify({"error": "Imagen no encontrada"}), 404
    return send_from_directory(DEVELOPED_DIR, subpath)


if __name__ == "__main__":
    import os
    # The interactive Werkzeug debugger is never enabled: it exposes an
    # interactive Python console on any unhandled exception.
    try:
        from waitress import serve

        serve(app, host="127.0.0.1", port=5050, threads=8, ident="Haluro")
    except ImportError:
        app.run(host="127.0.0.1", port=5050, debug=False)
