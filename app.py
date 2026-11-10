"""Flask backend application for Haluro — Laboratorio Analógico Digital.
Provides REST API for 72-stock film emulation, optical negative density inversion,
real-time cached previews, lossless multi-format export, and contact sheets.
"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import functools
import io
import json
import logging
import os
import time
import uuid
import zipfile
import base64
import numpy as np
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from PIL import Image

from engine import __version__, APP_NAME, about_payload
from engine.updater import check_for_updates, open_external_url
from engine.films import list_films, get_film, LUT_DIR
from engine.pipeline import (
    develop_frame,
    format_analog_caption,
    load_image_linear,
    linear_to_srgb,
    save_output_image,
    RAW_EXTENSIONS,
    HEIF_EXTENSIONS,
)
from engine.contact_sheet import generate_contact_sheet
from engine.negative_inverter import (
    process_negative_to_image,
    auto_detect_film_base,
    analyze_roll_calibration,
    compute_neutral_wb_from_point,
    auto_balance_scene_wb,
    linear_rgb_to_hex,
    list_profiles as list_negative_profiles,
    list_print_finishes,
    list_bw_toners,
    MINILAB_PROFILES,
    LIGHT_SOURCE_MATRICES,
    TONE_VARIANTS,
    SCAN_SOURCES,
    COLOR_METHODS,
    SHARPEN_MODES,
    PRINT_FINISHES,
    BW_TONING_PROFILES,
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

logger = logging.getLogger(__name__)

RESOURCE_ROOT = get_resource_root()
USER_DATA_ROOT = get_user_data_root()
SAMPLES_DIR = (RESOURCE_ROOT / "samples").resolve()
UPLOAD_DIR = (USER_DATA_ROOT / "uploads").resolve()
DEVELOPED_DIR = (USER_DATA_ROOT / "developed").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEVELOPED_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_OUTPUT_EXTS = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "tiff": ".tiff", "tif": ".tiff"}

app = Flask(
    __name__,
    template_folder=str(RESOURCE_ROOT / "templates"),
    static_folder=str(RESOURCE_ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB max per upload


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
        "frame-ancestors 'none';",
    )
    return response


@app.errorhandler(413)
def _handle_payload_too_large(_err):
    return jsonify({"error": "El archivo supera el límite máximo permitido (300 MB)."}), 413


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


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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
        "profile_key": data.get("profile", "frontier"),
        "light_source": light_src,
        "scan_source": scan_src,
        "pre_saturation": float(data.get("pre_saturation", 1.0)),
        "color_method": color_meth,
        "roll_bounds": roll_bounds,
        "tone_variant": tone_var,
        "print_finish": p_finish,
        "finish_amount": float(data.get("finish_amount", 1.0)),
        "bw_toner": bw_toner,
        "bw_toner_strength": float(data.get("bw_toner_strength", 1.0)),
        "brightness": float(data.get("brightness", 0.0)),
        "midtone_nd": float(data.get("midtone_nd", 0.0)),
        "contrast": float(data.get("contrast", 0.0)),
        "push_pull": float(data.get("push_pull", 0.0)),
        "lights": float(data.get("lights", 0.0)),
        "darks": float(data.get("darks", 0.0)),
        "whites": float(data.get("whites", 0.0)),
        "blacks": float(data.get("blacks", 0.0)),
        "black_clip": float(data.get("black_clip", 0.0)),
        "white_clip": float(data.get("white_clip", 0.0)),
        "clip_protect": bool(data.get("clip_protect", True)),
        "inky_blacks": float(data.get("inky_blacks", 0.0)),
        "sat_mult": float(data.get("saturation", 1.0)),
        "rp_tone": float(data.get("rp_tone", 0.0)),
        "border_buffer": float(data.get("border_buffer", 0.06)),
        "crop_pct": float(data.get("crop_pct", 0.0)),
        "glow_mult": float(data.get("glow", 1.0)),
        "fade_mult": float(data.get("fade", 1.0)),
        "printer_cyan_red": float(printer_cmy[0]),
        "printer_magenta_green": float(printer_cmy[1]),
        "printer_yellow_blue": float(printer_cmy[2]),
        "temp": float(data.get("temp", 0.0)),
        "tint": float(data.get("tint", 0.0)),
        "warming_85": float(data.get("warming_85", 0.0)),
        "skylight_filter": float(data.get("skylight_filter", 0.0)),
        "shade_filter": float(data.get("shade_filter", 0.0)),
        "shadows_tint": _parse_triplet(data.get("shadows_tint")),
        "mids_tint": _parse_triplet(data.get("mids_tint")),
        "highs_tint": _parse_triplet(data.get("highs_tint")),
        "shadows_range": float(data.get("shadows_range", 0.5)),
        "highs_range": float(data.get("highs_range", 0.5)),
        "sharpen_mode": sharp_mode,
        "sharpen_amount": float(data.get("sharpen_amount", 1.0)),
        "rotate": int(data.get("rotate", 0)),
        "flip_h": bool(data.get("flip_h", False)),
    }


def _record_history_entry(pil_img, final_saved_path: Path, meta: dict):
    """Save a preview JPEG & recipe sidecar in DEVELOPED_DIR for non-destructive version history."""
    preview_name = f"{final_saved_path.stem}.jpg"
    preview_copy = DEVELOPED_DIR / preview_name
    pil_img.save(preview_copy, format="JPEG", quality=92)
    meta_out = {
        **meta,
        "saved_path": str(final_saved_path),
        "output_format": final_saved_path.suffix.lstrip(".").upper(),
        "output_resolution": f"{pil_img.width}x{pil_img.height}",
        "developed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_path = DEVELOPED_DIR / f"{final_saved_path.stem}.meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_out, f, indent=2, ensure_ascii=False)
    return meta_out


# -------------------------------------------------------------
# CORE STUDIO & FILM EMULATION ROUTES
# -------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", about=about_payload())


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


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún archivo"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Nombre de archivo vacío"}), 400

    filename = _sanitize_filename(f.filename)
    save_path = UPLOAD_DIR / filename
    # Avoid overwriting different uploads with identical names if needed
    f.save(save_path)

    suffix_lower = save_path.suffix.lower()
    is_raw = suffix_lower in RAW_EXTENSIONS
    is_heif = suffix_lower in HEIF_EXTENSIONS
    return jsonify({
        "filename": filename,
        "name": f.filename,
        "is_raw": is_raw,
        "is_heif": is_heif,
        "size_bytes": save_path.stat().st_size,
        "thumb_url": f"/api/thumbnail/{filename}",
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
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
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
    filenames = data.get("filenames", ["SAMPLE.CR2"])
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
    flip_h = bool(data.get("flip_h", False))
    gen_sheet = bool(data.get("sheet", True))
    out_ext = _normalize_ext(data.get("format", "jpg"))
    roll_name = secure_filename(data.get("roll_name", "ROLL_001")) or "ROLL_001"

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
        f_film = fr.get("film", film_key) if isinstance(fr, dict) else film_key
        f_ev = float(fr.get("ev", ev)) if isinstance(fr, dict) else ev
        f_hal = float(fr.get("halation", halation)) if isinstance(fr, dict) else halation
        f_grn = float(fr.get("grain", grain)) if isinstance(fr, dict) else grain
        f_vig = float(fr.get("vignette", vignette)) if isinstance(fr, dict) else vignette
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = int(fr.get("rotate", rotate)) if isinstance(fr, dict) else rotate
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
        return (out_name, dev_img)

    max_workers = min(4, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_develop_one, filenames))
    else:
        results = [_develop_one(fn) for fn in filenames]

    developed_images = []
    output_files = []
    for res in results:
        if res:
            out_name, dev_img = res
            output_files.append(out_name)
            developed_images.append(dev_img)

    sheet_created = False
    if gen_sheet and developed_images:
        sheet = generate_contact_sheet(
            developed_images,
            roll_name=roll_name,
            film_name=film_info["name"],
        )
        sheet_path = out_roll_dir / "SHEET.jpg"
        sheet.save(sheet_path, quality=93, subsampling=0)
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
    filenames = data.get("filenames", ["SAMPLE.CR2"])
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
    flip_h = bool(data.get("flip_h", False))
    roll_name = secure_filename(data.get("roll_name", "PREVIEW")) or "PREVIEW"

    film_info = get_film(film_key)
    per_frame_recipes = data.get("per_frame_recipes") or {}
    t_start = time.time()

    def _render_thumb(fname):
        fpath = _resolve_source_file(fname)
        if not fpath:
            return None
        fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None
        f_film = fr.get("film", film_key) if isinstance(fr, dict) else film_key
        f_ev = float(fr.get("ev", ev)) if isinstance(fr, dict) else ev
        f_hal = float(fr.get("halation", halation)) if isinstance(fr, dict) else halation
        f_grn = float(fr.get("grain", grain)) if isinstance(fr, dict) else grain
        f_vig = float(fr.get("vignette", vignette)) if isinstance(fr, dict) else vignette
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = int(fr.get("rotate", rotate)) if isinstance(fr, dict) else rotate
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

    max_workers = min(6, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            rendered_images = [img for img in executor.map(_render_thumb, filenames) if img is not None]
    else:
        rendered_images = [img for fn in filenames if (img := _render_thumb(fn)) is not None]

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet = generate_contact_sheet(
        rendered_images,
        roll_name=roll_name,
        film_name=film_info["name"],
        thumb_width=480,
    )

    cache_dir = DEVELOPED_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sheet_cache_path = cache_dir / "sheet_preview.jpg"
    sheet.save(sheet_cache_path, format="JPEG", quality=90)

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "sheet": True,
        "sheet_url": f"/api/image/cache/sheet_preview.jpg?t={int(time.time() * 1000)}",
        "total_frames": len(rendered_images),
        "width": sheet.width,
        "height": sheet.height,
        "elapsed_seconds": elapsed,
    })


@app.route("/api/save_contact_sheet", methods=["POST"])
def api_save_contact_sheet():
    """Render archival high-resolution contact sheet only and save directly or to chosen path."""
    data = request.json or {}
    filenames = data.get("filenames", ["SAMPLE.CR2"])
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
    flip_h = bool(data.get("flip_h", False))
    reveal = bool(data.get("reveal", True))
    roll_name = secure_filename(data.get("roll_name", "HALURO_ROLL")) or "HALURO_ROLL"

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
        f_film = fr.get("film", film_key) if isinstance(fr, dict) else film_key
        f_ev = float(fr.get("ev", ev)) if isinstance(fr, dict) else ev
        f_hal = float(fr.get("halation", halation)) if isinstance(fr, dict) else halation
        f_grn = float(fr.get("grain", grain)) if isinstance(fr, dict) else grain
        f_vig = float(fr.get("vignette", vignette)) if isinstance(fr, dict) else vignette
        f_date = bool(fr.get("date", add_date)) if isinstance(fr, dict) else add_date
        f_rot = int(fr.get("rotate", rotate)) if isinstance(fr, dict) else rotate
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

    max_workers = min(6, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            rendered_images = [img for img in executor.map(_render_thumb, filenames) if img is not None]
    else:
        rendered_images = [img for fn in filenames if (img := _render_thumb(fn)) is not None]

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet = generate_contact_sheet(
        rendered_images,
        roll_name=roll_name,
        film_name=film_info["name"],
        thumb_width=960,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target_path, format="JPEG", quality=94, subsampling=0)

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
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
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
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
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
    film_key = data.get("film", "portra400")
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
    film_key = data.get("film", "portra400")
    ev = float(data.get("ev", 0.0))
    halation = float(data.get("halation", 1.0))
    grain = float(data.get("grain", 1.0))
    vignette = float(data.get("vignette", 1.0))
    add_date = bool(data.get("date", False))
    rotate = int(data.get("rotate", 0))
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
    dest = Path(dest_path)
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
            except Exception:
                pass

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
    filenames = data.get("filenames") or ["SAMPLE_NEGATIVE.jpg"]
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
        rot = int(fr.get("rotate", params["rotate"])) if isinstance(fr, dict) else params["rotate"]
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

    dest = UPLOAD_DIR / "SAMPLE_NEGATIVE.jpg"
    if not dest.is_file() or sample_file.stat().st_mtime > dest.stat().st_mtime:
        import shutil
        shutil.copy2(sample_file, dest)

    return jsonify({
        "filename": "SAMPLE_NEGATIVE.jpg",
        "name": "Kodak Gold 200 (Escaneo C-41)",
        "is_raw": False,
        "size_bytes": dest.stat().st_size,
        "thumb_url": "/api/thumbnail/SAMPLE_NEGATIVE.jpg",
    })


@app.route("/api/negative/auto_detect_base", methods=["POST"])
def api_negative_auto_detect_base():
    data = request.json or {}
    filename = data.get("filename", "SAMPLE_NEGATIVE.jpg")
    rotate = int(data.get("rotate", 0))
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
    x_pct = float(data.get("x_pct", data.get("x", 0.5)))
    y_pct = float(data.get("y_pct", data.get("y", 0.5)))
    rotate = int(data.get("rotate", 0))
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
    x_pct = float(data.get("x_pct", data.get("x", 0.5)))
    y_pct = float(data.get("y_pct", data.get("y", 0.5)))

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
        crop_milli = int(round(params["crop_pct"] * 1000))
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
    profile_key = data.get("profile", "frontier")
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
    filenames = data.get("filenames", ["SAMPLE_NEGATIVE.jpg"])
    gen_sheet = bool(data.get("sheet", True))
    out_ext = _normalize_ext(data.get("format", "jpg"))
    roll_name = secure_filename(data.get("roll_name", "NEG_ROLL_001")) or "NEG_ROLL_001"

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

        f_prof_key = frame_params["profile_key"]
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
        return (out_name, pos_img)

    max_workers = min(4, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_develop_one, filenames))
    else:
        results = [_develop_one(fn) for fn in filenames]

    developed_images = []
    output_files = []
    for res in results:
        if res:
            out_name, pos_img = res
            output_files.append(out_name)
            developed_images.append(pos_img)

    sheet_created = False
    if gen_sheet and developed_images:
        sheet = generate_contact_sheet(
            developed_images,
            roll_name=roll_name,
            film_name=f"Negativo · {profile_info['name']}",
        )
        sheet_path = out_roll_dir / "SHEET.jpg"
        sheet.save(sheet_path, quality=93, subsampling=0)
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
    filenames = data.get("filenames", ["SAMPLE_NEGATIVE.jpg"])
    roll_name = secure_filename(data.get("roll_name", "PREVIEW_NEG")) or "PREVIEW_NEG"

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

    max_workers = min(6, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            rendered_images = [img for img in executor.map(_render_thumb, filenames) if img is not None]
    else:
        rendered_images = [img for fn in filenames if (img := _render_thumb(fn)) is not None]

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet = generate_contact_sheet(
        rendered_images,
        roll_name=roll_name,
        film_name=f"Negativo · {profile_info['name']}",
        thumb_width=480,
    )

    cache_dir = DEVELOPED_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sheet_cache_path = cache_dir / "sheet_preview.jpg"
    sheet.save(sheet_cache_path, format="JPEG", quality=90)

    elapsed = round(time.time() - t_start, 2)
    return jsonify({
        "success": True,
        "sheet": True,
        "sheet_url": f"/api/image/cache/sheet_preview.jpg?t={int(time.time() * 1000)}",
        "total_frames": len(rendered_images),
        "width": sheet.width,
        "height": sheet.height,
        "elapsed_seconds": elapsed,
    })


@app.route("/api/negative/save_contact_sheet", methods=["POST"])
def api_negative_save_contact_sheet():
    """Render archival high-resolution negative contact sheet only and save directly or to chosen path."""
    data = request.json or {}
    filenames = data.get("filenames", ["SAMPLE_NEGATIVE.jpg"])
    roll_name = secure_filename(data.get("roll_name", "HALURO_NEG")) or "HALURO_NEG"
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

    max_workers = min(6, max(1, os.cpu_count() or 1))
    if len(filenames) > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            rendered_images = [img for img in executor.map(_render_thumb, filenames) if img is not None]
    else:
        rendered_images = [img for fn in filenames if (img := _render_thumb(fn)) is not None]

    if not rendered_images:
        return jsonify({"error": "No se pudieron procesar fotogramas para la hoja"}), 400

    sheet = generate_contact_sheet(
        rendered_images,
        roll_name=roll_name,
        film_name=f"Negativo · {profile_info['name']}",
        thumb_width=960,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target_path, format="JPEG", quality=94, subsampling=0)

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
    debug_mode = os.environ.get("HALURO_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=5050, debug=debug_mode)
