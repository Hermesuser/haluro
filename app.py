"""Flask backend application for Haluro — Laboratorio Analógico Digital.
Provides REST API for 80-stock film emulation, optical negative density inversion,
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from engine import APP_NAME, __version__, about_payload
from engine.contact_sheet import generate_contact_sheet
from engine.films import (
    LUT_DIR,
    VALID_GRAIN_ASAS,
    clear_user_luts,
    delete_user_lut,
    get_film,
    get_hidden_films,
    get_user_luts_dir,
    hide_builtin_film,
    list_films,
    restore_hidden_films,
    save_user_lut,
)
from engine.negative_inverter import (
    BW_TONING_PROFILES,
    COLOR_METHODS,
    FILM_SUBSTRATES,
    LIGHT_SOURCE_MATRICES,
    MINILAB_PROFILES,
    PRINT_FINISHES,
    SCAN_SOURCES,
    SHARPEN_MODES,
    TONE_VARIANTS,
    analyze_roll_calibration,
    auto_balance_scene_wb,
    auto_detect_film_base,
    compute_flat_field_gain_map,
    compute_neutral_wb_from_point,
    linear_rgb_to_hex,
    list_bw_toners,
    list_film_substrates,
    list_print_finishes,
    process_negative_to_image,
    resolve_flat_field_gain,
)
from engine.negative_inverter import (
    list_profiles as list_negative_profiles,
)
from engine.pipeline import (
    DEV_PROCESSES,
    HEIF_EXTENSIONS,
    RAW_EXTENSIONS,
    VALID_BW_FILTERS,
    VALID_DUAL_HIGHLIGHT_TONERS,
    VALID_DUAL_SHADOW_TONERS,
    VALID_ENLARGER_HEADS,
    VALID_PAPER_BASES,
    VALID_PAPER_DEVELOPERS,
    VALID_ZONE_DEVS,
    develop_frame,
    extract_source_exif,
    format_analog_caption,
    get_srgb_icc_bytes,
    linear_to_srgb,
    load_image_linear,
    normalize_crop_rect,
    resolve_export_extension,
    save_output_image,
    write_geometry_xmp_sidecar,
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
from engine.presets import (
    PresetError,
    delete_preset,
    import_presets_payload,
    list_presets,
    save_preset,
)
from engine.projects import (
    ProjectError,
    collect_protected_filenames,
    delete_project,
    export_project_archive,
    import_project_archive,
    list_projects,
    load_project,
    rename_project,
    resolve_project_media_file,
    save_project,
    validate_project_id,
)
from engine.updater import check_for_updates, open_external_url

logger = logging.getLogger(__name__)

RESOURCE_ROOT = get_resource_root()
USER_DATA_ROOT = get_user_data_root()
SAMPLES_DIR = (RESOURCE_ROOT / "samples").resolve()
UPLOAD_DIR = (USER_DATA_ROOT / "uploads").resolve()
DEVELOPED_DIR = (USER_DATA_ROOT / "developed").resolve()
PROJECTS_DIR = (USER_DATA_ROOT / "projects").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEVELOPED_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_OUTPUT_EXTS = {
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "png": ".png",
    "tiff": ".tiff",
    "tif": ".tiff",
    "dng": ".dng",
    "webp": ".webp",
}
ALLOWED_INPUT_EXTS = RAW_EXTENSIONS | HEIF_EXTENSIONS | {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}

# Workspace hygiene: uploads are transient working copies, not an archive.
UPLOAD_RETENTION_DAYS = 30
UPLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Workspace hygiene: the developed archive (previews + recipe sidecars) also
# needs retention, otherwise it grows without bound on every export.
DEVELOPED_RETENTION_DAYS = 90
DEVELOPED_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB


def _prune_workspace() -> None:
    """Drop stale uploads and trim the workspace to a size budget.

    The upload folder grew without bound (467 MB on a single workstation) and
    every export added another preview to the developed archive.
    """
    cutoff = time.time() - (UPLOAD_RETENTION_DAYS * 86400)
    protected = collect_protected_filenames(PROJECTS_DIR)
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
        if item.name in protected:
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


def _prune_developed_dir() -> None:
    """Drop stale developed previews and sidecars to keep the archive bounded."""
    cutoff = time.time() - (DEVELOPED_RETENTION_DAYS * 86400)
    try:
        entries = sorted(DEVELOPED_DIR.glob("*"), key=lambda p: p.stat().st_mtime)
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
        if total <= DEVELOPED_MAX_BYTES:
            break
        try:
            size = item.stat().st_size
            item.unlink()
            total -= size
        except OSError:
            continue


_prune_workspace()
_prune_developed_dir()

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
def _load_or_create_api_token() -> str:
    """Lee el token de sesión desde disco o crea uno nuevo y lo persiste.

    El token se genera una vez por instalación y se reutiliza entre reinicios,
    de modo que el frontend no pierde la sesión cada vez que se reinicia el
    backend. Se almacena en el directorio de datos del usuario
    (`USER_DATA_ROOT / "session.token"`).
    """
    token_file = USER_DATA_ROOT / "session.token"
    try:
        if token_file.is_file():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    try:
        token_file.write_text(token, encoding="utf-8")
    except OSError:
        # Si no se puede escribir (permisos, solo lectura), se usa en memoria
        # solo para esta sesión.
        pass
    return token


API_TOKEN = _load_or_create_api_token()
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", "::1"]

# Guard against decompression bombs: Pillow refuses images above this size.
Image.MAX_IMAGE_PIXELS = 120_000_000  # 120 MP ≈ 480 MB per float32 RGB array

# Maximum number of frames a single batch request may queue.
MAX_BATCH_FRAMES = 200
# Maximum number of concurrent full-resolution developments (memory bound).
MAX_FULL_RES_WORKERS = 2

# --- Export destination allow-list -------------------------------------------
# Rutas enviadas por JSON (no vía diálogo nativo) deben residir dentro de
# alguna de estas raíces. Esto evita que un cliente escriba en directorios
# sensibles del sistema (p. ej. /etc, ~/Library, C:\Windows).
EXPORT_ALLOWED_ROOTS = (DEVELOPED_DIR, get_downloads_dir())

# Rutas aprobadas explícitamente por el usuario mediante diálogo nativo
# ("Guardar como…"). Se identifican por un token de vida corta para evitar
# que un tercero reutilice una ruta antigua.
_dialog_approved_paths: dict[str, Path] = {}
_DIALOG_TOKEN_TTL_SECONDS = 300  # 5 minutos


def _approve_dialog_path(path: Path | str) -> str:
    """Registra una ruta elegida por diálogo nativo y devuelve un token de uso único."""
    token = secrets.token_urlsafe(16)
    _dialog_approved_paths[token] = Path(path).expanduser().resolve()
    return token


def _consume_dialog_token(token: str | None) -> Path | None:
    """Consume y devuelve la ruta asociada a un token de diálogo, o None si es inválido/expiró."""
    if not token:
        return None
    path = _dialog_approved_paths.pop(token, None)
    return path


# --- Rate limiting simple (ventana fija por endpoint e IP) -------------------
# El backend solo escucha en loopback, pero un script local o una pestaña
# maliciosa podrían saturar los 8 hilos de Waitress con revelados full-res.
_rate_limit_state: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # segundos
_RATE_LIMIT_MAX = {
    "/api/upload": 30,
    "/api/develop_full": 10,
    "/api/negative/develop_full": 10,
    "/api/batch/develop_roll_start": 5,
    "/api/export_single": 20,
    "/api/export_and_download": 20,
    "/api/save_direct_to_downloads": 20,
    "/api/save_to_path": 20,
    "/api/save_zip_to_downloads": 10,
    "/api/negative/save_to_downloads": 20,
    "/api/negative/save_to_path": 20,
    "/api/negative/save_contact_sheet": 10,
    "/api/negative/contact_sheet_preview": 20,
    "/api/contact_sheet_preview": 20,
}


def _rate_limited(path: str) -> bool:
    """Devuelve True si se superó el cupo de peticiones para `path` en la ventana actual."""
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    timestamps = _rate_limit_state.get(path, [])
    timestamps = [t for t in timestamps if t > window_start]
    max_allowed = _RATE_LIMIT_MAX.get(path, 60)
    if len(timestamps) >= max_allowed:
        _rate_limit_state[path] = timestamps
        return True
    timestamps.append(now)
    _rate_limit_state[path] = timestamps
    return False


@app.after_request
def _apply_security_headers(response):
    """Apply defense-in-depth HTTP security headers to all responses.

    Self-hosted fonts & assets ensure 100% offline privacy with zero external telemetry.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), payment=(), usb=(), "
        "magnetometer=(), gyroscope=(), accelerometer=()",
    )
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

    # Rate limiting para operaciones de escritura pesada (evita DoS local)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.path in _RATE_LIMIT_MAX and _rate_limited(request.path):
            return jsonify(
                {"error": "Demasiadas peticiones a este endpoint. Inténtelo de nuevo más tarde."}
            ), 429
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


def _normalize_ext(fmt_str, source_path=None):
    return resolve_export_extension(fmt_str, source_path=source_path)


def _parse_geometry_params(data: dict) -> dict:
    """Extract and validate unified geometry parameters for Simulation & Negative modes."""
    return {
        "rotate": _int(data, "rotate", 0, 0, 360),
        "flip_h": bool(data.get("flip_h", False)),
        "flip_v": bool(data.get("flip_v", False)),
        "straighten": _num(data, "straighten", 0.0, -45.0, 45.0),
        "keystone_v": _num(data, "keystone_v", 0.0, -30.0, 30.0),
        "keystone_h": _num(data, "keystone_h", 0.0, -30.0, 30.0),
        "crop_rect": normalize_crop_rect(data.get("crop_rect")),
        "auto_crop_straighten": bool(data.get("auto_crop_straighten", True)),
    }


def _validate_destination_path(
    raw_path: str,
    dialog_token: str | None = None,
) -> tuple[Path | None, str | None]:
    """Validate user export destination path.

    El destino debe tener una extensión de imagen permitida y residir dentro de
    una raíz autorizada (`DEVELOPED_DIR` o `~/Downloads`), salvo que presente un
    token de diálogo nativo válido y no expirado (ruta elegida explícitamente
    por el usuario mediante "Guardar como…").
    """
    if not raw_path or not isinstance(raw_path, str):
        return None, "Ruta de destino inválida o vacía."
    try:
        dest = Path(raw_path).expanduser().resolve()
    except Exception as exc:
        return None, f"Ruta de destino no válida: {exc}"

    ext = dest.suffix.lower()
    allowed_exts = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".dng", ".webp"}
    if ext not in ALLOWED_OUTPUT_EXTS.values() and ext not in allowed_exts:
        return None, f"Extensión de archivo no permitida ({ext}). Use .jpg, .png, .tiff o .dng."

    # 1. Ruta aprobada por diálogo nativo (token de un solo uso)
    approved = _consume_dialog_token(dialog_token)
    if approved is not None:
        if dest == approved:
            parent = dest.parent
            if not parent.exists():
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    return None, f"No se puede crear la carpeta de destino: {exc}"
            return dest, None
        return None, "El destino no coincide con la ruta aprobada por el diálogo."

    # 2. Ruta dentro de las raíces permitidas
    for root in EXPORT_ALLOWED_ROOTS:
        try:
            dest.relative_to(root)
        except ValueError:
            continue
        parent = dest.parent
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return None, f"No se puede crear la carpeta de destino: {exc}"
        return dest, None

    return None, (
        "Directorio de destino no permitido. Use ~/Downloads, la carpeta de "
        "revelados de la aplicación o elija una ubicación con el diálogo nativo."
    )


# Presupuesto de memoria para la caché de previews originales (base64 en RAM).
# Cada entrada puede ocupar varios cientos de KB; limitamos el total a ~48 MB
# y el número de entradas a 12 para evitar presión de memoria en sesiones largas.
_CACHED_ORIGINAL_MAX_BYTES = 48 * 1024 * 1024
_cached_original_bytes_total = 0


@functools.lru_cache(maxsize=12)
def _cached_original_b64_cached(
    resolved_path_str,
    mtime_ns,
    max_dim,
    rotate,
    flip_h,
    crop_milli=0,
    flip_v=False,
    straighten_milli=0,
    keystone_v_milli=0,
    keystone_h_milli=0,
    crop_rect_key=None,
    auto_crop_straighten=True,
):
    """Encode original reference preview once and serve from RAM on subsequent slider moves."""
    lin = load_image_linear(
        resolved_path_str,
        max_dim=max_dim,
        rotate=rotate,
        flip_h=flip_h,
        flip_v=flip_v,
        straighten=straighten_milli / 1000.0,
        keystone_v=keystone_v_milli / 1000.0,
        keystone_h=keystone_h_milli / 1000.0,
        crop_rect=crop_rect_key,
        auto_crop_straighten=auto_crop_straighten,
    )
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


def _cached_original_b64(
    resolved_path_str,
    mtime_ns,
    max_dim,
    rotate,
    flip_h,
    crop_milli=0,
    flip_v=False,
    straighten=0.0,
    keystone_v=0.0,
    keystone_h=0.0,
    crop_rect=None,
    auto_crop_straighten=True,
):
    """Wrapper con control de presupuesto de bytes para la caché de previews originales."""
    global _cached_original_bytes_total
    crop_key = tuple(round(v, 5) for v in crop_rect) if crop_rect is not None else None
    result = _cached_original_b64_cached(
        resolved_path_str,
        mtime_ns,
        max_dim,
        rotate,
        flip_h,
        crop_milli,
        bool(flip_v),
        int(round(float(straighten or 0.0) * 1000)),
        int(round(float(keystone_v or 0.0) * 1000)),
        int(round(float(keystone_h or 0.0) * 1000)),
        crop_key,
        bool(auto_crop_straighten),
    )
    # Estimación del tamaño de la entrada (base64 ≈ 4/3 del binario).
    entry_size = len(result) * 3 // 4
    _cached_original_bytes_total += entry_size
    if _cached_original_bytes_total > _CACHED_ORIGINAL_MAX_BYTES:
        _cached_original_b64_cached.cache_clear()
        _cached_original_bytes_total = 0
    return result


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


def _parse_print_options(data):
    """Validate optional darkroom easel border & paper dry-down compensation."""
    allowed = {"none", "white_thin", "white_gallery", "gallery_caption", "black_rebate"}
    border = str((data or {}).get("easel_border", "none") or "none").strip().lower()
    if border not in allowed:
        border = "none"
    dry_down = _num(data or {}, "dry_down_comp", 0.0, 0.0, 0.15)
    return border, dry_down


def _parse_export_profile(data):
    """Validate optional export max dimension (px) and JPEG quality (60-100)."""
    src = data if isinstance(data, dict) else {}
    raw_dim = src.get("export_max_dim")
    max_dim = None
    if raw_dim not in (None, "", 0, "0", "original"):
        try:
            parsed = int(raw_dim)
            if 512 <= parsed <= 16000:
                max_dim = parsed
        except (TypeError, ValueError):
            max_dim = None
    quality = _int(src, "jpeg_quality", 96, 60, 100)
    return max_dim, quality


def _parse_local_masks(raw):
    """Validate linear-gradient and radial Dodge & Burn local exposure masks."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        mtype = str(item.get("type", "linear") or "linear").lower()
        if mtype not in ("linear", "radial"):
            mtype = "linear"
        mmode = str(item.get("mode", "exposure") or "exposure").lower()
        if mmode not in ("exposure", "farmer"):
            mmode = "exposure"
        try:
            x1 = max(-0.5, min(1.5, float(item.get("x1", 0.5))))
            y1 = max(-0.5, min(1.5, float(item.get("y1", 0.25))))
            x2 = max(-0.5, min(1.5, float(item.get("x2", 0.5))))
            y2 = max(-0.5, min(1.5, float(item.get("y2", 0.75))))
            ev = max(-2.5, min(2.5, float(item.get("ev", 0.0))))
            feather = max(0.05, min(1.0, float(item.get("feather", 0.4))))
        except (TypeError, ValueError):
            continue
        cleaned.append(
            {
                "type": mtype,
                "mode": mmode,
                "x1": round(x1, 4),
                "y1": round(y1, 4),
                "x2": round(x2, 4),
                "y2": round(y2, 4),
                "ev": round(ev, 3),
                "feather": round(feather, 3),
                "invert": bool(item.get("invert", False)),
            }
        )
    return cleaned


def _parse_shared_optics_params(data: dict) -> dict:
    """Extract shared denoise, defringe, sharpen, dust spots, and local Dodge & Burn masks."""
    sharp_mode = str(data.get("sharpen_mode", "off") or "off")
    if sharp_mode not in SHARPEN_MODES:
        sharp_mode = "off"
    return {
        "denoise_luma": _num(data, "denoise_luma", 0.0, 0.0, 1.0),
        "denoise_chroma": _num(data, "denoise_chroma", 0.0, 0.0, 1.0),
        "defringe": _num(data, "defringe", 0.0, 0.0, 1.0),
        "sharpen_mode": sharp_mode,
        "sharpen_amount": _num(data, "sharpen_amount", 1.0, 0.0, 3.0),
        "dust_spots": _parse_dust_spots(data.get("dust_spots")),
        "local_masks": _parse_local_masks(data.get("local_masks")),
    }


def _parse_dust_spots(raw):
    """Validate normalized pinpoint dust spots: [{x, y, r}, ...] or [[x, y, r], ...]."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[:150]:
        if isinstance(item, dict):
            x_raw, y_raw, r_raw = item.get("x"), item.get("y"), item.get("r", 0.008)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x_raw, y_raw = item[0], item[1]
            r_raw = item[2] if len(item) >= 3 else 0.008
        else:
            continue
        try:
            x = float(x_raw)
            y = float(y_raw)
            r = float(r_raw)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            continue
        r = max(0.002, min(0.045, r))
        cleaned.append({"x": round(x, 5), "y": round(y, 5), "r": round(r, 5)})
    return cleaned


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
    film_sub = str(data.get("film_substrate", "c41_orange") or "c41_orange")
    if film_sub not in FILM_SUBSTRATES:
        film_sub = "c41_orange"
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

    raw_ff = str(data.get("flat_field_file", "") or "").strip()
    ff_path = _resolve_source_file(raw_ff) if raw_ff else None

    return {
        "base_color": data.get("base_color"),
        "flat_field_file": ff_path.name if ff_path else None,
        "flat_field_path": ff_path,
        "flat_field_strength": _num(data, "flat_field_strength", 1.0, 0.0, 1.5),
        "film_type": data.get("film_type", "color"),
        "film_substrate": film_sub,
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
        "bw_grade00": _num(data, "bw_grade00", 0.0, -1.0, 1.0),
        "bw_grade5": _num(data, "bw_grade5", 0.0, -1.0, 1.0),
        "bw_preflash": _num(data, "bw_preflash", 0.0, 0.0, 1.0),
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
        "keep_sprockets": bool(data.get("keep_sprockets", False)),
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
        "denoise_luma": _num(data, "denoise_luma", 0.0, 0.0, 1.0),
        "denoise_chroma": _num(data, "denoise_chroma", 0.0, 0.0, 1.0),
        "defringe": _num(data, "defringe", 0.0, 0.0, 1.0),
        "local_masks": _parse_local_masks(data.get("local_masks")),
        **_parse_geometry_params(data),
        "curve": _parse_curve(data.get("curve")),
        "dust_spots": _parse_dust_spots(data.get("dust_spots")),
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
    return jsonify({
        "films": list_films(),
        "hidden_count": len(get_hidden_films()),
        "dev_processes": [{"key": k, "name": v["name"]} for k, v in DEV_PROCESSES.items()],
    })


@app.route("/api/films/<path:key>", methods=["DELETE"])
def api_delete_film(key):
    """Remove a user LUT from disk or hide a built-in emulsion from the catalog."""
    if key.startswith("user:"):
        if not delete_user_lut(key):
            return jsonify({"error": "LUT de usuario no encontrado."}), 404
        return jsonify({
            "success": True,
            "removed_type": "user_lut",
            "films": list_films(),
            "hidden_count": len(get_hidden_films()),
        })

    try:
        removed = hide_builtin_film(key)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not removed:
        return jsonify({"error": "Emulsión no encontrada en el catálogo."}), 404
    return jsonify({
        "success": True,
        "removed_type": "builtin",
        "films": list_films(),
        "hidden_count": len(get_hidden_films()),
    })


@app.route("/api/films/restore_hidden", methods=["POST"])
def api_restore_hidden_films():
    """Restore one or all hidden built-in emulsions back into the catalog."""
    data = request.json or {}
    key = data.get("key")
    restored = restore_hidden_films(key=str(key) if key else None)
    return jsonify({
        "success": True,
        "restored": restored,
        "films": list_films(),
        "hidden_count": len(get_hidden_films()),
    })


@app.route("/api/user_luts", methods=["POST"])
def api_upload_user_luts():
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return jsonify({"error": "No se recibieron archivos .cube"}), 400

    lut_space = (request.form.get("lut_space") or "srgb").strip().lower()
    added = []
    errors = []

    for f in files:
        fname = f.filename or ""
        if not fname:
            continue
        try:
            raw = f.read()
            if not raw:
                raise ValueError("El archivo está vacío.")
            film_entry = save_user_lut(fname, raw, lut_space=lut_space)
            added.append(film_entry)
        except ValueError as exc:
            errors.append({"filename": fname, "error": str(exc)})
        except Exception as exc:
            logger.exception("Error importando LUT %s", fname)
            errors.append({"filename": fname, "error": f"Error inesperado: {exc}"})

    if not added and errors:
        return jsonify({
            "success": False,
            "added": [],
            "errors": errors,
            "error": errors[0]["error"],
        }), 400

    return jsonify({
        "success": True,
        "added": added,
        "errors": errors,
        "films": list_films(),
    })


@app.route("/api/user_luts/<path:key>", methods=["DELETE"])
def api_delete_user_lut(key):
    if not delete_user_lut(key):
        return jsonify({"error": "LUT de usuario no encontrado"}), 404
    return jsonify({"success": True, "films": list_films(), "hidden_count": len(get_hidden_films())})


@app.route("/api/user_luts", methods=["DELETE"])
def api_clear_user_luts():
    """Remove all custom `.cube` LUTs from `user_luts/`."""
    removed = clear_user_luts()
    return jsonify({
        "success": True,
        "removed": removed,
        "films": list_films(),
        "hidden_count": len(get_hidden_films()),
    })


@app.route("/api/user_luts/open_folder", methods=["POST"])
def api_open_user_luts_folder():
    user_dir = get_user_luts_dir()
    open_directory(user_dir)
    return jsonify({"success": True, "path": str(user_dir)})


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
        "source_exif": extract_source_exif(save_path),
    })


@app.route("/api/prefetch", methods=["POST"])
def api_prefetch():
    """Warm thumbnail and linear preview caches for adjacent frames in the background."""
    data = request.json or {}
    filenames = data.get("filenames")
    if not isinstance(filenames, list):
        return jsonify({"warmed": 0})
    warmed = 0
    for fname in filenames[:4]:
        fpath = _resolve_source_file(str(fname or ""))
        if not fpath or not fpath.is_file():
            continue
        try:
            _cached_thumb_bytes(str(fpath), fpath.stat().st_mtime_ns)
            warmed += 1
        except Exception as exc:
            logger.debug("Prefetch omitido para %s: %s", fpath.name, exc)
            continue
    return jsonify({"warmed": warmed})


@app.route("/api/thumbnail/<filename>")
def api_thumbnail(filename):
    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Miniatura no encontrada"}), 404
    jpeg_bytes = _cached_thumb_bytes(str(fpath), fpath.stat().st_mtime_ns)
    return send_file(io.BytesIO(jpeg_bytes), mimetype="image/jpeg", max_age=3600)


# --- Curva tonal de usuario ---------------------------------------------------
# La curva viaja como DATOS (puntos de control), no como píxeles: así cabe en la
# receta por fotograma, se copia, se sincroniza con el rollo y se exporta sin
# tocar ningún otro mecanismo de la aplicación.
_CURVE_CHANNELS = ("rgb", "r", "g", "b", "l")
_MAX_CURVE_POINTS = 32


def _parse_curve(value):
    """Valida y normaliza una curva de usuario: dict canal -> lista de [x, y].

    Devuelve ``None`` si la curva es vacía o inválida (la imagen no se toca).
    """
    if not isinstance(value, dict) or not value:
        return None
    out = {}
    for channel in _CURVE_CHANNELS:
        pts = value.get(channel)
        if not isinstance(pts, (list, tuple)) or not pts:
            continue
        clean = []
        for p in list(pts)[:_MAX_CURVE_POINTS]:
            try:
                x = float(p[0])
                y = float(p[1])
            except (TypeError, ValueError, IndexError):
                continue
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            clean.append([
                round(min(max(x, 0.0), 1.0), 5),
                round(min(max(y, -0.5), 1.5), 5),
            ])
        if clean:
            out[channel] = clean
    return out or None


def _parse_dev_process(value) -> str:
    s = str(value or "standard").strip()
    return s if s in DEV_PROCESSES else "standard"


def _parse_grain_asa(value) -> str:
    s = str(value or "auto").strip().lower()
    return s if s in VALID_GRAIN_ASAS else "auto"


def _parse_sim_look_params(data: dict, fallback: dict | None = None) -> dict:
    """Parse film strength, WB, B&W filter, Zone System N-2..N+2, enlarger head, B&W print, dual toner & Farmer."""
    src = data if isinstance(data, dict) else {}
    fb = fallback if isinstance(fallback, dict) else {}
    raw_strength = src.get("film_strength", fb.get("film_strength", 1.0))
    raw_temp = src.get("sim_temp", fb.get("sim_temp", 0.0))
    raw_tint = src.get("sim_tint", fb.get("sim_tint", 0.0))
    raw_bw = str(src.get("bw_filter", fb.get("bw_filter", "none")) or "none").strip().lower()
    raw_zone = str(src.get("zone_dev", fb.get("zone_dev", "N")) or "N").strip().upper()
    raw_head = str(src.get("enlarger_head", fb.get("enlarger_head", "standard")) or "standard").strip().lower()
    raw_pdev = str(src.get("paper_dev", fb.get("paper_dev", "neutral")) or "neutral").strip().lower()
    raw_pbase = str(src.get("paper_base", fb.get("paper_base", "none")) or "none").strip().lower()
    raw_tsh = str(src.get("toner_shadows", fb.get("toner_shadows", "none")) or "none").strip().lower()
    raw_thi = str(src.get("toner_highlights", fb.get("toner_highlights", "none")) or "none").strip().lower()
    return {
        "film_strength": _num({"v": raw_strength}, "v", 1.0, 0.0, 1.0),
        "sim_temp": _num({"v": raw_temp}, "v", 0.0, -1.0, 1.0),
        "sim_tint": _num({"v": raw_tint}, "v", 0.0, -1.0, 1.0),
        "bw_filter": raw_bw if raw_bw in VALID_BW_FILTERS else "none",
        "zone_dev": raw_zone if raw_zone in VALID_ZONE_DEVS else "N",
        "enlarger_head": raw_head if raw_head in VALID_ENLARGER_HEADS else "standard",
        "paper_dev": raw_pdev if raw_pdev in VALID_PAPER_DEVELOPERS else "neutral",
        "paper_base": raw_pbase if raw_pbase in VALID_PAPER_BASES else "none",
        "bw_grade00": _num({"v": src.get("bw_grade00", fb.get("bw_grade00", 0.0))}, "v", 0.0, -1.0, 1.0),
        "bw_grade5": _num({"v": src.get("bw_grade5", fb.get("bw_grade5", 0.0))}, "v", 0.0, -1.0, 1.0),
        "bw_preflash": _num({"v": src.get("bw_preflash", fb.get("bw_preflash", 0.0))}, "v", 0.0, 0.0, 1.0),
        "toner_shadows": raw_tsh if raw_tsh in VALID_DUAL_SHADOW_TONERS else "none",
        "toner_shadows_amt": _num(
            {"v": src.get("toner_shadows_amt", fb.get("toner_shadows_amt", 0.0))}, "v", 0.0, 0.0, 1.0
        ),
        "toner_highlights": raw_thi if raw_thi in VALID_DUAL_HIGHLIGHT_TONERS else "none",
        "toner_highlights_amt": _num(
            {"v": src.get("toner_highlights_amt", fb.get("toner_highlights_amt", 0.0))}, "v", 0.0, 0.0, 1.0
        ),
        "farmer_bleach": _num({"v": src.get("farmer_bleach", fb.get("farmer_bleach", 0.0))}, "v", 0.0, 0.0, 1.0),
    }


@app.route("/api/preview", methods=["POST"])
def api_preview():
    data = request.json or {}
    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
    sim_look = _parse_sim_look_params(data)
    add_date = bool(data.get("date", False))
    geom = _parse_geometry_params(data)
    optics = _parse_shared_optics_params(data)
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
        grain_asa=grain_asa,
        vignette_mult=vignette,
        shadows=shadows,
        mids=mids,
        highlights=highlights,
        curve=curve,
        add_date=add_date,
        max_dim=1280,
        dev_process=dev_process,
        **sim_look,
        **geom,
        **optics,
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
        resp["source_exif"] = extract_source_exif(file_path)
        resp["original"] = _cached_original_b64(
            str(file_path),
            file_path.stat().st_mtime_ns,
            1280,
            geom["rotate"],
            geom["flip_h"],
            0,
            flip_v=geom["flip_v"],
            straighten=geom["straighten"],
            keystone_v=geom["keystone_v"],
            keystone_h=geom["keystone_h"],
            crop_rect=geom["crop_rect"],
            auto_crop_straighten=geom["auto_crop_straighten"],
        )
    return jsonify(resp)


def _format_ev_strip_label(delta_ev: float, is_third_step: bool) -> str:
    if abs(delta_ev) < 1e-3:
        return "0 EV"
    sign = "+" if delta_ev > 0 else "-"
    if is_third_step:
        thirds = int(round(abs(delta_ev) * 3))
        whole = thirds // 3
        rem = thirds % 3
        if rem == 0:
            return f"{sign}{whole} EV"
        if whole == 0:
            return f"{sign}{rem}/3 EV"
        return f"{sign}{whole} {rem}/3 EV"
    return f"{sign}{abs(delta_ev):.1f} EV"


@app.route("/api/test_strip", methods=["POST"])
def api_test_strip():
    """Genera una tira de prueba en 5 pasos f-stop (estilo ampliadora de cuarto oscuro)."""
    data = request.json or {}
    mode = "negative" if data.get("mode") == "negative" else "simulation"
    default_sample = "SAMPLE_NEGATIVE.jpg" if mode == "negative" else "SAMPLE.CR2"
    filename = data.get("filename", default_sample)
    file_path = _resolve_source_file(filename, fallback_name=default_sample)
    if not file_path:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    step_ev = _num(data, "step_ev", 0.5, 0.15, 1.0)
    is_third = abs(step_ev - (1.0 / 3.0)) < 0.04 or abs(step_ev - 0.333) < 0.02
    if is_third:
        step_ev = 1.0 / 3.0

    t0 = time.time()
    offsets = [-2.0 * step_ev, -step_ev, 0.0, step_ev, 2.0 * step_ev]

    if mode == "negative":
        params = _parse_negative_params(data)
        lin_base = load_image_linear(
            file_path,
            max_dim=840,
            rotate=params["rotate"],
            flip_h=params["flip_h"],
        )
        base_bright = float(params["brightness"])
        # Pre-resolve flat field gain at target orientation once
        resolved_ff = resolve_flat_field_gain(
            flat_field_path=params.get("flat_field_path"),
            rotate=params["rotate"],
            flip_h=params["flip_h"],
        )
        strip_params = dict(params)
        strip_params["rotate"] = 0
        strip_params["flip_h"] = False
        strip_params["flat_field_path"] = None
        strip_params["flat_field_gain"] = resolved_ff
    else:
        film_key = _canonical_film_key(data.get("film", "portra400"))
        ev_base = _num(data, "ev", 0.0, -10.0, 10.0)
        halation = _num(data, "halation", 1.0, 0.0, 5.0)
        grain = _num(data, "grain", 1.0, 0.0, 5.0)
        grain_asa = _parse_grain_asa(data.get("grain_asa"))
        vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
        shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
        mids = _num(data, "mids", 0.0, -4.0, 4.0)
        highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
        curve = _parse_curve(data.get("curve"))
        dev_process = _parse_dev_process(data.get("dev_process"))
        add_date = bool(data.get("date", False))
        rotate = _int(data, "rotate", 0, 0, 360)
        flip_h = bool(data.get("flip_h", False))
        lin_base = load_image_linear(file_path, max_dim=840, rotate=rotate, flip_h=flip_h)

    h, w = lin_base.shape[:2]
    composite = np.zeros((h, w, 3), dtype=np.uint8)
    steps_meta = []
    n_cols = len(offsets)

    for idx, delta_ev in enumerate(offsets):
        x0 = int(round(idx * w / n_cols))
        x1 = int(round((idx + 1) * w / n_cols)) if idx < n_cols - 1 else w
        if mode == "negative":
            target_val = float(np.clip(base_bright + delta_ev * 0.28, -1.0, 1.0))
            step_params = dict(strip_params, brightness=target_val)
            col_img = process_negative_to_image(lin_base.copy(), max_dim=None, **step_params)
        else:
            target_val = float(np.clip(ev_base + delta_ev, -10.0, 10.0))
            col_img = develop_frame(
                lin_base.copy(),
                film_key=film_key,
                ev_adjust=target_val,
                halation_mult=halation,
                grain_mult=grain,
                grain_asa=grain_asa,
                vignette_mult=vignette,
                shadows=shadows,
                mids=mids,
                highlights=highlights,
                curve=curve,
                add_date=add_date,
                max_dim=None,
                rotate=0,
                flip_h=False,
                dev_process=dev_process,
            )
        col_arr = np.asarray(col_img.convert("RGB"), dtype=np.uint8)
        composite[:, x0:x1, :] = col_arr[:, x0:x1, :]
        if idx > 0 and x0 < w:
            composite[:, max(0, x0 - 1) : x0 + 1, :] = 18
        steps_meta.append({
            "index": idx,
            "delta_ev": round(delta_ev, 4),
            "label": _format_ev_strip_label(delta_ev, is_third),
            "target_value": round(target_val, 3),
        })

    strip_pil = Image.fromarray(composite)
    buf = io.BytesIO()
    strip_pil.save(buf, format="JPEG", quality=89)
    strip_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    return jsonify({
        "strip": strip_b64,
        "width": w,
        "height": h,
        "step_ev": round(step_ev, 4),
        "steps": steps_meta,
        "render_time": round(time.time() - t0, 3),
    })


@app.route("/api/develop_full", methods=["POST"])
def api_develop_full():
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE.CR2"]))
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
    add_date = bool(data.get("date", False))
    geom = _parse_geometry_params(data)
    gen_sheet = bool(data.get("sheet", True))
    raw_fmt = str(data.get("format", "jpg") or "jpg").strip().lower()
    out_ext = "original" if raw_fmt == "original" else _normalize_ext(raw_fmt)
    raw_roll_name = str(data.get("roll_name", "ROLL 001")).strip()[:40] or "ROLL 001"
    roll_name = secure_filename(raw_roll_name) or "ROLL_001"
    columns = _int(data, "columns", 4, 2, 8)

    film_info = get_film(film_key)
    out_roll_dir = DEVELOPED_DIR / f"{roll_name}_{film_key}"
    out_roll_dir.mkdir(parents=True, exist_ok=True)

    analog_meta = _parse_analog_meta(data)
    easel_border, dry_down_comp = _parse_print_options(data)
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
        f_asa = _parse_grain_asa(fr.get("grain_asa", grain_asa)) if isinstance(fr, dict) else grain_asa
        f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
        f_shadows = _num(fr, "shadows", shadows, -4.0, 4.0) if isinstance(fr, dict) else shadows
        f_mids = _num(fr, "mids", mids, -4.0, 4.0) if isinstance(fr, dict) else mids
        f_highlights = _num(fr, "highlights", highlights, -4.0, 4.0) if isinstance(fr, dict) else highlights
        f_curve = _parse_curve(fr.get("curve")) if isinstance(fr, dict) else curve
        f_dev_proc = _parse_dev_process(fr.get("dev_process", dev_process)) if isinstance(fr, dict) else dev_process
        f_sim_look = _parse_sim_look_params(fr, fallback=data) if isinstance(fr, dict) else _parse_sim_look_params(data)
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_geom = _parse_geometry_params({**geom, **fr}) if isinstance(fr, dict) else geom
        f_optics = (
            _parse_shared_optics_params({**data, **fr})
            if isinstance(fr, dict)
            else _parse_shared_optics_params(data)
        )
        f_ext = resolve_export_extension(out_ext, source_path=fpath)

        dev_img, srgb_f = develop_frame(
            fpath,
            film_key=f_film,
            ev_adjust=f_ev,
            halation_mult=f_hal,
            grain_mult=f_grn,
            grain_asa=f_asa,
            vignette_mult=f_vig,
            shadows=f_shadows,
            mids=f_mids,
            highlights=f_highlights,
            curve=f_curve,
            add_date=f_date,
            max_dim=None,
            return_float=True,
            dev_process=f_dev_proc,
            **f_sim_look,
            **f_geom,
            **f_optics,
        )
        out_name = f"{fpath.stem}_{f_film}{f_ext}"
        target_path = out_roll_dir / out_name
        save_output_image(
            dev_img,
            target_path,
            source_path=fpath,
            quality=96,
            float_srgb=srgb_f,
            analog_meta=analog_meta,
            easel_border=easel_border,
            dry_down_comp=dry_down_comp,
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
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
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
        f_asa = _parse_grain_asa(fr.get("grain_asa", grain_asa)) if isinstance(fr, dict) else grain_asa
        f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
        f_shadows = _num(fr, "shadows", shadows, -4.0, 4.0) if isinstance(fr, dict) else shadows
        f_mids = _num(fr, "mids", mids, -4.0, 4.0) if isinstance(fr, dict) else mids
        f_highlights = _num(fr, "highlights", highlights, -4.0, 4.0) if isinstance(fr, dict) else highlights
        f_curve = _parse_curve(fr.get("curve")) if isinstance(fr, dict) else curve
        f_dev_proc = _parse_dev_process(fr.get("dev_process", dev_process)) if isinstance(fr, dict) else dev_process
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = _int(fr, "rotate", rotate, 0, 360) if isinstance(fr, dict) else rotate
        f_flip = bool(fr.get("flip_h", flip_h)) if isinstance(fr, dict) else flip_h

        return develop_frame(
            fpath,
            film_key=f_film,
            ev_adjust=f_ev,
            halation_mult=f_hal,
            grain_mult=f_grn,
            grain_asa=f_asa,
            vignette_mult=f_vig,
            shadows=f_shadows,
            mids=f_mids,
            highlights=f_highlights,
            curve=f_curve,
            add_date=f_date,
            max_dim=720,
            rotate=f_rot,
            flip_h=f_flip,
            dev_process=f_dev_proc,
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
    # Nombre único por request: evita que dos peticiones concurrentes se
    # sobrescriban la hoja de contacto de preview.
    sheet_cache_path = cache_dir / f"sheet_preview_simulation_{uuid.uuid4().hex[:12]}.jpg"
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
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
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
        f_asa = _parse_grain_asa(fr.get("grain_asa", grain_asa)) if isinstance(fr, dict) else grain_asa
        f_vig = _num(fr, "vignette", vignette, 0.0, 5.0) if isinstance(fr, dict) else vignette
        f_shadows = _num(fr, "shadows", shadows, -4.0, 4.0) if isinstance(fr, dict) else shadows
        f_mids = _num(fr, "mids", mids, -4.0, 4.0) if isinstance(fr, dict) else mids
        f_highlights = _num(fr, "highlights", highlights, -4.0, 4.0) if isinstance(fr, dict) else highlights
        f_curve = _parse_curve(fr.get("curve")) if isinstance(fr, dict) else curve
        f_dev_proc = _parse_dev_process(fr.get("dev_process", dev_process)) if isinstance(fr, dict) else dev_process
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = _int(fr, "rotate", rotate, 0, 360) if isinstance(fr, dict) else rotate
        f_flip = bool(fr.get("flip_h", flip_h)) if isinstance(fr, dict) else flip_h

        return develop_frame(
            fpath,
            film_key=f_film,
            ev_adjust=f_ev,
            halation_mult=f_hal,
            grain_mult=f_grn,
            grain_asa=f_asa,
            vignette_mult=f_vig,
            shadows=f_shadows,
            mids=f_mids,
            highlights=f_highlights,
            curve=f_curve,
            add_date=f_date,
            max_dim=1400,
            rotate=f_rot,
            flip_h=f_flip,
            dev_process=f_dev_proc,
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
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
    add_date = bool(data.get("date", False))
    geom = _parse_geometry_params(data)
    optics = _parse_shared_optics_params(data)
    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    out_ext = _normalize_ext(data.get("format", "jpg"), source_path=fpath)
    film_info = get_film(film_key)
    out_filename = f"{fpath.stem}_{film_key}{out_ext}"
    target_path = DEVELOPED_DIR / out_filename

    analog_meta = _parse_analog_meta(data)
    easel_border, dry_down_comp = _parse_print_options(data)
    export_max_dim, jpeg_quality = _parse_export_profile(data)
    sim_look = _parse_sim_look_params(data)
    t0 = time.time()
    dev_img, srgb_f = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        grain_asa=grain_asa,
        vignette_mult=vignette,
        shadows=shadows,
        mids=mids,
        highlights=highlights,
        curve=curve,
        add_date=add_date,
        max_dim=None,
        return_float=True,
        dev_process=dev_process,
        **sim_look,
        **geom,
        **optics,
    )
    dev_img = save_output_image(
        dev_img,
        target_path,
        source_path=fpath,
        quality=jpeg_quality,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
        easel_border=easel_border,
        dry_down_comp=dry_down_comp,
        export_max_dim=export_max_dim,
    )
    if bool(data.get("write_xmp", False)):
        write_geometry_xmp_sidecar(
            target_path,
            rotate=geom["rotate"],
            flip_h=geom["flip_h"],
            flip_v=geom["flip_v"],
            straighten=geom["straighten"],
            crop_rect=geom["crop_rect"],
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
        **geom,
        "dev_process": dev_process,
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
    grain_asa = _parse_grain_asa(request.args.get("grain_asa"))
    vignette = float(request.args.get("vignette", 1.0))
    shadows = float(request.args.get("shadows", 0.0))
    mids = float(request.args.get("mids", 0.0))
    highlights = float(request.args.get("highlights", 0.0))
    try:
        _curve_arg = json.loads(request.args.get("curve", "null"))
    except (TypeError, ValueError):
        _curve_arg = None
    curve = _parse_curve(_curve_arg)
    dev_process = _parse_dev_process(request.args.get("dev_process"))
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
        grain_asa=grain_asa,
        vignette_mult=vignette,
        shadows=shadows,
        mids=mids,
        highlights=highlights,
        curve=curve,
        add_date=add_date,
        max_dim=None,
        dev_process=dev_process,
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
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
    add_date = bool(data.get("date", False))
    geom = _parse_geometry_params(data)
    optics = _parse_shared_optics_params(data)
    reveal = bool(data.get("reveal", True))

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    out_ext = _normalize_ext(data.get("format", "jpg"), source_path=fpath)
    film_info = get_film(film_key)
    downloads_dir = get_downloads_dir()

    stem_base = f"{fpath.stem}_{film_key}"
    target_path = downloads_dir / f"{stem_base}{out_ext}"
    counter = 1
    while target_path.exists():
        target_path = downloads_dir / f"{stem_base}_{counter}{out_ext}"
        counter += 1

    analog_meta = _parse_analog_meta(data)
    easel_border, dry_down_comp = _parse_print_options(data)
    export_max_dim, jpeg_quality = _parse_export_profile(data)
    sim_look = _parse_sim_look_params(data)
    t0 = time.time()
    dev_img, srgb_f = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        grain_asa=grain_asa,
        vignette_mult=vignette,
        shadows=shadows,
        mids=mids,
        highlights=highlights,
        curve=curve,
        add_date=add_date,
        max_dim=None,
        return_float=True,
        dev_process=dev_process,
        **sim_look,
        **geom,
        **optics,
    )
    dev_img = save_output_image(
        dev_img,
        target_path,
        source_path=fpath,
        quality=jpeg_quality,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
        easel_border=easel_border,
        dry_down_comp=dry_down_comp,
        export_max_dim=export_max_dim,
    )
    if bool(data.get("write_xmp", False)):
        write_geometry_xmp_sidecar(
            target_path,
            rotate=geom["rotate"],
            flip_h=geom["flip_h"],
            flip_v=geom["flip_v"],
            straighten=geom["straighten"],
            crop_rect=geom["crop_rect"],
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
        **geom,
        "dev_process": dev_process,
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
    token = _approve_dialog_path(chosen)
    return jsonify({"chosen_path": chosen, "dialog_token": token, "cancelled": False})


@app.route("/api/native_save_dialog", methods=["POST"])
def api_native_save_dialog():
    """Backward-compatible native save dialog for simulation mode across macOS and Windows 11."""
    data = request.json or {}
    if "default_name" in data and "film" not in data:
        return api_choose_save_path()

    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    out_ext = _normalize_ext(data.get("format", "jpg"), source_path=fpath)
    default_name = f"{fpath.stem}_{film_key}{out_ext}"
    chosen = choose_save_path_dialog(default_name)
    if not chosen:
        return jsonify({"cancelled": True})

    token = _approve_dialog_path(chosen)
    data_with_dest = {**data, "dest_path": chosen, "dialog_token": token}
    return _save_simulation_to_dest(data_with_dest, reveal=True)


def _save_simulation_to_dest(data, reveal=False):
    dest_path = data.get("dest_path")
    dialog_token = data.get("dialog_token")
    dest, err = _validate_destination_path(dest_path, dialog_token=dialog_token)
    if err:
        return jsonify({"error": err}), 400
    filename = data.get("filename", "SAMPLE.CR2")
    film_key = _canonical_film_key(data.get("film", "portra400"))
    ev = _num(data, "ev", 0.0, -10.0, 10.0)
    halation = _num(data, "halation", 1.0, 0.0, 5.0)
    grain = _num(data, "grain", 1.0, 0.0, 5.0)
    grain_asa = _parse_grain_asa(data.get("grain_asa"))
    vignette = _num(data, "vignette", 1.0, 0.0, 5.0)
    shadows = _num(data, "shadows", 0.0, -4.0, 4.0)
    mids = _num(data, "mids", 0.0, -4.0, 4.0)
    highlights = _num(data, "highlights", 0.0, -4.0, 4.0)
    curve = _parse_curve(data.get("curve"))
    dev_process = _parse_dev_process(data.get("dev_process"))
    add_date = bool(data.get("date", False))
    geom = _parse_geometry_params(data)
    optics = _parse_shared_optics_params(data)

    fpath = _resolve_source_file(filename)
    if not fpath:
        return jsonify({"error": "Archivo de origen no encontrado"}), 404

    film_info = get_film(film_key)
    analog_meta = _parse_analog_meta(data)
    easel_border, dry_down_comp = _parse_print_options(data)
    sim_look = _parse_sim_look_params(data)
    t0 = time.time()
    dev_img, srgb_f = develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=ev,
        halation_mult=halation,
        grain_mult=grain,
        grain_asa=grain_asa,
        vignette_mult=vignette,
        shadows=shadows,
        mids=mids,
        highlights=highlights,
        curve=curve,
        add_date=add_date,
        max_dim=None,
        return_float=True,
        dev_process=dev_process,
        **sim_look,
        **geom,
        **optics,
    )
    # Use the *validated* destination. Re-deriving it from the raw payload
    # discarded the expanduser()/resolve() normalisation and wrote to a literal
    # "~" directory inside the working folder.
    dev_img = save_output_image(
        dev_img,
        dest,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
        easel_border=easel_border,
        dry_down_comp=dry_down_comp,
    )
    if bool(data.get("write_xmp", False)):
        write_geometry_xmp_sidecar(
            dest,
            rotate=geom["rotate"],
            flip_h=geom["flip_h"],
            flip_v=geom["flip_v"],
            straighten=geom["straighten"],
            crop_rect=geom["crop_rect"],
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
        **geom,
        "dev_process": dev_process,
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
# SAVED ROLL PROJECTS (Persistent Non-Destructive Sessions)
# -------------------------------------------------------------

@app.route("/api/projects", methods=["GET"])
def api_list_projects():
    """List all saved digital roll projects sorted by last update."""
    return jsonify({"projects": list_projects(PROJECTS_DIR)})


@app.route("/api/projects", methods=["POST"])
def api_save_project():
    """Create or update a saved roll project with all per-frame recipes and media."""
    data = request.json or {}
    try:
        result = save_project(
            PROJECTS_DIR,
            data,
            upload_dir=UPLOAD_DIR,
            samples_dir=SAMPLES_DIR,
            app_version=__version__,
            resolve_source_file=_resolve_source_file,
        )
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, **result})


@app.route("/api/projects/<project_id>", methods=["GET"])
def api_load_project(project_id):
    """Load a saved roll project and restore its media files into the active workspace."""
    try:
        result = load_project(
            PROJECTS_DIR,
            project_id,
            upload_dir=UPLOAD_DIR,
            samples_dir=SAMPLES_DIR,
        )
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError:
        return jsonify({"error": "Proyecto no encontrado."}), 404
    return jsonify({"success": True, **result})


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def api_rename_project(project_id):
    """Rename a saved roll project or update its notes."""
    data = request.json or {}
    try:
        summary = rename_project(
            PROJECTS_DIR,
            project_id,
            new_name=data.get("name", ""),
            notes=data.get("notes") if "notes" in data else None,
        )
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError:
        return jsonify({"error": "Proyecto no encontrado."}), 404
    return jsonify({"success": True, "project": summary})


@app.route("/api/projects/<project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    """Delete a saved roll project and its protected media copies."""
    try:
        deleted = delete_project(PROJECTS_DIR, project_id)
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400
    if not deleted:
        return jsonify({"error": "Proyecto no encontrado."}), 404
    return jsonify({"success": True})


@app.route("/api/projects/<project_id>/thumb", methods=["GET"])
def api_project_thumb(project_id):
    """Serve the cover thumbnail of a saved roll project."""
    try:
        pid = validate_project_id(project_id)
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400

    manifest_path = (PROJECTS_DIR / pid / "project.json").resolve()
    if not _is_within(manifest_path, PROJECTS_DIR) or not manifest_path.is_file():
        return jsonify({"error": "Miniatura de proyecto no encontrada."}), 404

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({"error": "Proyecto ilegible."}), 404

    frames = data.get("frames") if isinstance(data.get("frames"), list) else []
    cover_name = None
    active_idx = data.get("active_frame_index", 0)
    if isinstance(active_idx, int) and 0 <= active_idx < len(frames):
        cover_name = frames[active_idx].get("filename")
    if not cover_name and frames:
        cover_name = frames[0].get("filename")
    if not cover_name:
        return jsonify({"error": "Proyecto sin fotogramas."}), 404

    fpath = resolve_project_media_file(PROJECTS_DIR, pid, cover_name) or _resolve_source_file(cover_name)
    if not fpath or not fpath.is_file():
        return jsonify({"error": "Archivo de miniatura no encontrado."}), 404

    jpeg_bytes = _cached_thumb_bytes(str(fpath), fpath.stat().st_mtime_ns)
    return send_file(io.BytesIO(jpeg_bytes), mimetype="image/jpeg", max_age=3600)


@app.route("/api/projects/<project_id>/export", methods=["GET"])
def api_export_project(project_id):
    """Download a portable `.haluro` archive containing the roll project and its media."""
    try:
        buf, download_name = export_project_archive(PROJECTS_DIR, project_id)
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError:
        return jsonify({"error": "Proyecto no encontrado."}), 404
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


@app.route("/api/projects/import", methods=["POST"])
def api_import_project():
    """Import a portable `.haluro` (ZIP) roll project into the local library."""
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo de proyecto."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Nombre de archivo vacío."}), 400
    try:
        summary = import_project_archive(
            PROJECTS_DIR,
            f.stream,
            allowed_media_exts=ALLOWED_INPUT_EXTS,
        )
    except ProjectError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "project": summary})


# -------------------------------------------------------------
# USER RECIPE PRESETS LIBRARY
# -------------------------------------------------------------

@app.route("/api/presets", methods=["GET"])
def api_list_presets():
    """List all saved user recipe presets."""
    return jsonify({"presets": list_presets(USER_DATA_ROOT)})


@app.route("/api/presets", methods=["POST"])
def api_save_preset():
    """Create or update a named user recipe preset."""
    data = request.json or {}
    try:
        entry = save_preset(
            USER_DATA_ROOT,
            name=data.get("name", ""),
            mode=data.get("mode", "simulation"),
            recipe=data.get("recipe") or {},
            notes=data.get("notes", ""),
            preset_id=data.get("id") or data.get("preset_id"),
        )
    except PresetError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "preset": entry, "presets": list_presets(USER_DATA_ROOT)})


@app.route("/api/presets/<preset_id>", methods=["DELETE"])
def api_delete_preset(preset_id):
    """Delete a saved user preset by ID."""
    try:
        deleted = delete_preset(USER_DATA_ROOT, preset_id)
    except PresetError as exc:
        return jsonify({"error": str(exc)}), 400
    if not deleted:
        return jsonify({"error": "Preset no encontrado."}), 404
    return jsonify({"success": True, "presets": list_presets(USER_DATA_ROOT)})


@app.route("/api/presets/export", methods=["GET"])
def api_export_presets():
    """Download all saved user presets as a portable JSON file."""
    payload = json.dumps({"version": 1, "presets": list_presets(USER_DATA_ROOT)}, ensure_ascii=False, indent=2)
    return send_file(
        io.BytesIO(payload.encode("utf-8")),
        mimetype="application/json",
        as_attachment=True,
        download_name="haluro_presets.json",
    )


@app.route("/api/presets/import", methods=["POST"])
def api_import_presets():
    """Import user presets from a JSON file upload or JSON body."""
    raw_data = None
    if "file" in request.files:
        f = request.files["file"]
        try:
            raw_data = json.loads(f.read().decode("utf-8"))
        except Exception:
            return jsonify({"error": "El archivo no es un JSON válido."}), 400
    else:
        raw_data = request.json
    try:
        added = import_presets_payload(USER_DATA_ROOT, raw_data)
    except PresetError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True, "added": added, "presets": list_presets(USER_DATA_ROOT)})


# -------------------------------------------------------------
# LOCAL STORAGE DIAGNOSTICS & SAFE CACHE CLEANUP
# -------------------------------------------------------------

def _dir_usage(directory: Path) -> dict:
    total_bytes = 0
    file_count = 0
    if directory.is_dir():
        for item in directory.rglob("*"):
            if item.is_file():
                try:
                    total_bytes += item.stat().st_size
                    file_count += 1
                except OSError:
                    continue
    return {"bytes": total_bytes, "files": file_count}


def _storage_summary() -> dict:
    uploads = _dir_usage(UPLOAD_DIR)
    developed = _dir_usage(DEVELOPED_DIR)
    projects = _dir_usage(PROJECTS_DIR)
    user_luts = _dir_usage(get_user_luts_dir())
    return {
        "uploads": uploads,
        "developed": developed,
        "projects": projects,
        "user_luts": user_luts,
        "total_bytes": uploads["bytes"] + developed["bytes"] + projects["bytes"] + user_luts["bytes"],
    }


@app.route("/api/storage", methods=["GET"])
def api_storage_info():
    """Return local disk usage across workspace folders."""
    return jsonify({"storage": _storage_summary()})


@app.route("/api/storage/clean", methods=["POST"])
def api_storage_clean():
    """Safely clear transient files in `uploads` (sparing saved projects) or `developed`."""
    data = request.json or {}
    target = str(data.get("target") or "").strip().lower()
    if target not in ("uploads", "developed"):
        return jsonify({"error": "Destino de limpieza no válido (usa 'uploads' o 'developed')."}), 400

    removed_files = 0
    freed_bytes = 0
    if target == "uploads":
        protected = collect_protected_filenames(PROJECTS_DIR)
        for item in list(UPLOAD_DIR.glob("*")):
            if item.is_file() and item.name not in protected and item.name != ".gitkeep":
                try:
                    sz = item.stat().st_size
                    item.unlink()
                    removed_files += 1
                    freed_bytes += sz
                except OSError:
                    continue
    else:
        for item in list(DEVELOPED_DIR.glob("*")):
            if item.is_file() and item.name != ".gitkeep":
                try:
                    sz = item.stat().st_size
                    item.unlink()
                    removed_files += 1
                    freed_bytes += sz
                except OSError:
                    continue

    return jsonify({
        "success": True,
        "target": target,
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "storage": _storage_summary(),
    })


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
        "film_substrates": list_film_substrates(),
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

    ff_gain = resolve_flat_field_gain(
        flat_field_path=params["flat_field_path"],
        rotate=params["rotate"],
        flip_h=params["flip_h"],
    )
    cal = analyze_roll_calibration(
        linear_frames,
        film_type=params["film_type"],
        light_source=params["light_source"],
        scan_source=params["scan_source"],
        pre_saturation=params["pre_saturation"],
        border_buffer=params["border_buffer"],
        film_substrate=params["film_substrate"],
        keep_sprockets=params["keep_sprockets"],
        flat_field_gain=ff_gain,
        flat_field_strength=params["flat_field_strength"],
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


@app.route("/api/negative/flat_field/upload", methods=["POST"])
def api_negative_flat_field_upload():
    """Upload a blank light-table frame to calibrate radial vignetting and LED shading."""
    if "file" not in request.files:
        return jsonify({"error": "No se recibió archivo de campo plano"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    raw_ext = Path(f.filename).suffix.lower()
    if raw_ext not in ALLOWED_INPUT_EXTS:
        return jsonify({"error": f"Formato no compatible ({raw_ext})."}), 400

    filename = _sanitize_filename(f.filename)
    save_path = _unique_upload_path(f"__haluro_flatfield_{filename}")
    f.save(save_path)

    suffix_lower = save_path.suffix.lower()
    is_raw = suffix_lower in RAW_EXTENSIONS
    is_heif = suffix_lower in HEIF_EXTENSIONS
    if not _is_readable_media(save_path, is_raw, is_heif):
        save_path.unlink(missing_ok=True)
        return jsonify({"error": "El archivo de campo plano no contiene una imagen válida."}), 400

    flat_lin = load_image_linear(save_path, max_dim=512)
    _gain_grid, metrics = compute_flat_field_gain_map(flat_lin, grid_size=64)
    return jsonify({
        "flat_field_file": save_path.name,
        "name": Path(f.filename).name,
        **metrics,
    })


@app.route("/api/negative/auto_detect_base", methods=["POST"])
def api_negative_auto_detect_base():
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    rotate = _int(data, "rotate", 0, 0, 360)
    flip_h = bool(data.get("flip_h", False))
    film_sub = str(data.get("film_substrate", "c41_orange") or "c41_orange")
    if film_sub not in FILM_SUBSTRATES:
        film_sub = "c41_orange"
    raw_ff = str(data.get("flat_field_file", "") or "").strip()
    ff_path = _resolve_source_file(raw_ff) if raw_ff else None
    ff_strength = _num(data, "flat_field_strength", 1.0, 0.0, 1.5)
    ff_gain = resolve_flat_field_gain(flat_field_path=ff_path, rotate=rotate, flip_h=flip_h)

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    lin = load_image_linear(fpath, max_dim=800, rotate=rotate, flip_h=flip_h)
    base_color = auto_detect_film_base(
        lin,
        film_substrate=film_sub,
        flat_field_gain=ff_gain,
        flat_field_strength=ff_strength,
    )
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
    ff_gain = resolve_flat_field_gain(
        flat_field_path=params["flat_field_path"],
        rotate=params["rotate"],
        flip_h=params["flip_h"],
    )
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
        film_substrate=params["film_substrate"],
        keep_sprockets=params["keep_sprockets"],
        flat_field_gain=ff_gain,
        flat_field_strength=params["flat_field_strength"],
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
    ff_gain = resolve_flat_field_gain(
        flat_field_path=params["flat_field_path"],
        rotate=params["rotate"],
        flip_h=params["flip_h"],
    )
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
        film_substrate=params["film_substrate"],
        keep_sprockets=params["keep_sprockets"],
        flat_field_gain=ff_gain,
        flat_field_strength=params["flat_field_strength"],
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
        skip_crop = bool(data.get("original_uncropped", False)) or params["keep_sprockets"]
        crop_milli = 0 if skip_crop else int(round(params["crop_pct"] * 1000))
        resp["original"] = _cached_original_b64(
            str(fpath),
            fpath.stat().st_mtime_ns,
            1280,
            params["rotate"],
            params["flip_h"],
            crop_milli,
            flip_v=params["flip_v"],
            straighten=0.0 if skip_crop else params["straighten"],
            keystone_v=0.0 if skip_crop else params["keystone_v"],
            keystone_h=0.0 if skip_crop else params["keystone_h"],
            crop_rect=None if skip_crop else params["crop_rect"],
            auto_crop_straighten=params["auto_crop_straighten"],
        )
    return jsonify(resp)


def _export_negative_common(data, target_path: Path, reveal: bool = False):
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    params = _parse_negative_params(data)
    analog_meta = _parse_analog_meta(data)
    easel_border, dry_down_comp = _parse_print_options(data)
    profile_key = params["profile_key"]
    profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])

    t0 = time.time()
    pos_img, srgb_f = process_negative_to_image(fpath, max_dim=None, return_float=True, **params)
    pos_img = save_output_image(
        pos_img,
        target_path,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
        easel_border=easel_border,
        dry_down_comp=dry_down_comp,
    )
    if bool(data.get("write_xmp", False)):
        write_geometry_xmp_sidecar(
            target_path,
            rotate=params["rotate"],
            flip_h=params["flip_h"],
            flip_v=params["flip_v"],
            straighten=params["straighten"],
            crop_rect=params["crop_rect"],
        )

    _record_history_entry(pos_img, target_path, {
        "mode": "negative_inversion",
        "source_original": str(fpath.name),
        "source_original_untouched": True,
        "profile_key": profile_key,
        "profile_name": profile_info["name"],
        "film_type": params["film_type"],
        "film_substrate": params["film_substrate"],
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
        "bw_grade00": params["bw_grade00"],
        "bw_grade5": params["bw_grade5"],
        "bw_preflash": params["bw_preflash"],
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
        "dust_spots": params.get("dust_spots", []),
        "border_buffer": params["border_buffer"],
        "crop_pct": params["crop_pct"],
        "keep_sprockets": params["keep_sprockets"],
        "flat_field_file": params["flat_field_file"],
        "flat_field_strength": params["flat_field_strength"],
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
        "curve": params["curve"],
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
    reveal = bool(data.get("reveal", True))

    fpath = _resolve_source_file(filename, fallback_name="SAMPLE_NEGATIVE.jpg")
    if not fpath:
        return jsonify({"error": "Archivo no encontrado"}), 404

    out_ext = _normalize_ext(data.get("format", "jpg"), source_path=fpath)

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
    dialog_token = data.get("dialog_token")
    dest, err = _validate_destination_path(dest_path, dialog_token=dialog_token)
    if err:
        return jsonify({"error": err}), 400
    return _export_negative_common(data, dest, reveal=False)


@app.route("/api/negative/develop_full", methods=["POST"])
def api_negative_develop_full():
    """Batch-invert an entire roll of scanned negatives and generate a positive contact sheet."""
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", ["SAMPLE_NEGATIVE.jpg"]))
    gen_sheet = bool(data.get("sheet", True))
    raw_fmt = str(data.get("format", "jpg") or "jpg").strip().lower()
    out_ext = "original" if raw_fmt == "original" else _normalize_ext(raw_fmt)
    raw_roll_name = str(data.get("roll_name", "NEG ROLL 001")).strip()[:40] or "NEG ROLL 001"
    roll_name = secure_filename(raw_roll_name) or "NEG_ROLL_001"
    columns = _int(data, "columns", 4, 2, 8)

    params = _parse_negative_params(data)
    analog_meta = _parse_analog_meta(data)
    easel_border, dry_down_comp = _parse_print_options(data)
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
        f_ext = resolve_export_extension(out_ext, source_path=fpath)
        pos_img, srgb_f = process_negative_to_image(fpath, max_dim=None, return_float=True, **frame_params)
        out_name = f"{fpath.stem}_positive_{f_prof_key}{f_ext}"
        target_path = out_roll_dir / out_name
        save_output_image(
            pos_img,
            target_path,
            source_path=fpath,
            quality=96,
            float_srgb=srgb_f,
            analog_meta=analog_meta,
            easel_border=easel_border,
            dry_down_comp=dry_down_comp,
        )
        if bool(data.get("write_xmp", False)):
            write_geometry_xmp_sidecar(
                target_path,
                rotate=frame_params["rotate"],
                flip_h=frame_params["flip_h"],
                flip_v=frame_params["flip_v"],
                straighten=frame_params["straighten"],
                crop_rect=frame_params["crop_rect"],
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
    # Nombre único por request: evita que dos peticiones concurrentes se
    # sobrescriban la hoja de contacto de preview.
    sheet_cache_path = cache_dir / f"sheet_preview_negative_{uuid.uuid4().hex[:12]}.jpg"
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
    dialog_token = data.get("dialog_token")
    if dest_path:
        target_path, err = _validate_destination_path(dest_path, dialog_token=dialog_token)
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


def _run_batch_roll_worker(job_id, data):
    """Ejecuta un trabajo de revelado de rollo delegando en RollBatchJob."""
    from engine.roll_processor import RollBatchJob

    job = RollBatchJob(job_id, data)
    job.run()

    with _batch_jobs_lock:
        _batch_jobs[job_id] = job


@app.route("/api/batch/develop_roll_start", methods=["POST"])
def api_batch_develop_roll_start():
    data = request.json or {}
    filenames = _bounded_frames(data.get("filenames", []))
    if not filenames:
        return jsonify({"error": "No hay fotogramas para procesar"}), 400

    job_id = str(uuid.uuid4())[:10]
    from engine.roll_processor import RollBatchJob

    with _batch_jobs_lock:
        if len(_batch_jobs) > 20:
            oldest = list(_batch_jobs.keys())[:-10]
            for k in oldest:
                _batch_jobs.pop(k, None)
        _batch_jobs[job_id] = RollBatchJob(job_id, data)

    t = threading.Thread(target=_run_batch_roll_worker, args=(job_id, data), daemon=True)
    t.start()
    return jsonify({"success": True, "job_id": job_id, "total": len(filenames)})


@app.route("/api/batch/develop_status/<job_id>", methods=["GET"])
def api_batch_develop_status(job_id):
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return jsonify({"status": "not_found", "error": "Trabajo no encontrado"}), 404
        payload = job.payload() if hasattr(job, "payload") else {k: v for k, v in job.items() if k != "cancel_event"}
    return jsonify(payload)


@app.route("/api/batch/develop_cancel/<job_id>", methods=["POST"])
def api_batch_develop_cancel(job_id):
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
        if not job:
            return jsonify({"success": False, "error": "Trabajo no encontrado"}), 404
        if hasattr(job, "cancel_event"):
            job.cancel_event.set()
            if job.status == "running":
                job.status = "cancelling"
                job.current_file = "Deteniendo hilos de procesamiento…"
        else:
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
