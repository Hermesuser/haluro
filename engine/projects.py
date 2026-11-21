"""Persistent roll project storage for Haluro — Laboratorio Analógico Digital.

Stores complete non-destructive digital roll projects (frame ordering, culling
status, per-frame film emulation & negative inversion recipes, roll-level
calibration, contact sheet configuration, and analog EXIF metadata) alongside
protected copies/hardlinks of each source image so photographers can safely
close the lab and resume their exact work at any time.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_SCHEMA_VERSION = 1
MAX_PROJECT_FRAMES = 200
MAX_PROJECT_NAME_LEN = 120
MAX_PROJECT_NOTES_LEN = 500
_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{4,80}$")


class ProjectError(ValueError):
    """Raised when a project operation receives invalid input."""


def validate_project_id(project_id: str) -> str:
    """Validate and return a safe project identifier (no path traversal)."""
    pid = str(project_id or "").strip()
    if not _PROJECT_ID_RE.match(pid):
        raise ProjectError("Identificador de proyecto no válido.")
    return pid


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generate_project_id() -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    suffix = uuid.uuid4().hex[:6]
    return f"proj_{stamp}_{suffix}"


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink `src` to `dst` when possible (0 extra disk space), else copy2."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if src.samefile(dst):
                return
        except OSError:
            pass
        try:
            dst.unlink()
        except OSError:
            pass
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, target)


def _clean_text(value: Any, max_len: int, default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return text[:max_len]


def _summarize_project(data: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    """Build a lightweight summary dict suitable for the Projects gallery."""
    frames = data.get("frames") if isinstance(data.get("frames"), list) else []
    app_mode = data.get("app_mode") if data.get("app_mode") in ("simulation", "negative") else "simulation"

    picked_count = 0
    rejected_count = 0
    edited_count = 0
    recipe_labels: list[str] = []
    seen_labels: set[str] = set()
    cover_filename: str | None = None

    active_idx = data.get("active_frame_index", 0)
    if isinstance(active_idx, int) and 0 <= active_idx < len(frames):
        cand = frames[active_idx]
        if isinstance(cand, dict) and cand.get("filename"):
            cover_filename = Path(str(cand["filename"])).name

    for frame in frames:
        if not isinstance(frame, dict):
            continue
        fname = Path(str(frame.get("filename") or "")).name
        if not cover_filename and fname:
            cover_filename = fname
        pick = frame.get("pickStatus")
        if pick == "pick":
            picked_count += 1
        elif pick == "reject":
            rejected_count += 1

        if app_mode == "negative":
            rec = frame.get("negRecipe")
            if isinstance(rec, dict) and rec:
                edited_count += 1
                lbl = str(rec.get("profile") or "").strip()
                if lbl and lbl not in seen_labels:
                    seen_labels.add(lbl)
                    recipe_labels.append(lbl)
        else:
            rec = frame.get("simRecipe")
            if isinstance(rec, dict) and rec:
                edited_count += 1
                lbl = str(rec.get("film") or "").strip()
                if lbl and lbl not in seen_labels:
                    seen_labels.add(lbl)
                    recipe_labels.append(lbl)

    pid = str(data.get("id") or project_dir.name)
    return {
        "id": pid,
        "name": _clean_text(data.get("name"), MAX_PROJECT_NAME_LEN, "Rollo sin título"),
        "notes": _clean_text(data.get("notes"), MAX_PROJECT_NOTES_LEN, ""),
        "app_mode": app_mode,
        "created_at": data.get("created_at") or "",
        "updated_at": data.get("updated_at") or "",
        "frame_count": len(frames),
        "picked_count": picked_count,
        "rejected_count": rejected_count,
        "edited_count": edited_count,
        "recipe_keys": recipe_labels[:5],
        "cover_filename": cover_filename,
        "cover_url": f"/api/projects/{pid}/thumb" if cover_filename else None,
        "project_dir": str(project_dir.resolve()),
    }


def list_projects(projects_dir: Path) -> list[dict[str, Any]]:
    """Return all saved roll projects sorted by `updated_at` descending."""
    if not projects_dir.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue
        manifest = entry / "project.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            summaries.append(_summarize_project(data, entry))
        except Exception as exc:
            logger.warning("Proyectos: no se pudo leer %s (%s)", manifest, exc)
            continue

    summaries.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return summaries


def collect_protected_filenames(projects_dir: Path) -> set[str]:
    """Collect every filename referenced by any saved project so workspace pruning spares them."""
    protected: set[str] = set()
    if not projects_dir.is_dir():
        return protected
    for entry in projects_dir.iterdir():
        manifest = entry / "project.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Proyectos: manifiesto ilegible en %s (%s)", manifest, exc)
            continue
        if not isinstance(data, dict):
            continue
        for frame in data.get("frames") or []:
            if isinstance(frame, dict) and frame.get("filename"):
                protected.add(Path(str(frame["filename"])).name)
        neg_roll = data.get("negative_roll")
        if isinstance(neg_roll, dict) and neg_roll.get("flat_field_file"):
            protected.add(Path(str(neg_roll["flat_field_file"])).name)
    return protected


def resolve_project_media_file(
    projects_dir: Path,
    project_id: str,
    filename: str,
) -> Path | None:
    """Safely locate a media file inside a project's `media/` directory."""
    pid = validate_project_id(project_id)
    safe_name = Path(filename or "").name
    if not safe_name:
        return None
    media_dir = (projects_dir / pid / "media").resolve()
    if not _is_within(media_dir, projects_dir):
        return None
    cand = (media_dir / safe_name).resolve()
    if _is_within(cand, media_dir) and cand.is_file():
        return cand
    return None


def save_project(
    projects_dir: Path,
    payload: dict[str, Any],
    *,
    upload_dir: Path,
    samples_dir: Path,
    app_version: str = "",
    resolve_source_file: Callable[[str], Path | None] | None = None,
) -> dict[str, Any]:
    """Create or update a saved roll project and protect all referenced media files."""
    if not isinstance(payload, dict):
        raise ProjectError("Cuerpo de proyecto no válido.")

    raw_frames = payload.get("frames")
    if not isinstance(raw_frames, list) or len(raw_frames) == 0:
        raise ProjectError("El rollo debe contener al menos un fotograma para guardarse.")
    if len(raw_frames) > MAX_PROJECT_FRAMES:
        raise ProjectError(f"Un proyecto admite como máximo {MAX_PROJECT_FRAMES} fotogramas.")

    raw_pid = payload.get("project_id") or payload.get("id")
    if raw_pid:
        pid = validate_project_id(str(raw_pid))
    else:
        pid = _generate_project_id()

    projects_dir.mkdir(parents=True, exist_ok=True)
    project_dir = (projects_dir / pid).resolve()
    if not _is_within(project_dir, projects_dir):
        raise ProjectError("Ruta de proyecto fuera del directorio permitido.")
    media_dir = project_dir / "media"
    manifest_path = project_dir / "project.json"

    existing_created_at = None
    if manifest_path.is_file():
        try:
            old_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(old_data, dict):
                existing_created_at = old_data.get("created_at")
        except Exception:
            existing_created_at = None

    now_iso = _utc_now_iso()
    default_name = time.strftime("Rollo %Y-%m-%d %H:%M", time.localtime())
    name = _clean_text(payload.get("name"), MAX_PROJECT_NAME_LEN, default_name)
    notes = _clean_text(payload.get("notes"), MAX_PROJECT_NOTES_LEN, "")
    app_mode = payload.get("app_mode") if payload.get("app_mode") in ("simulation", "negative") else "simulation"

    def _find_source(fname: str) -> Path | None:
        safe = Path(fname or "").name
        if not safe:
            return None
        if resolve_source_file is not None:
            found = resolve_source_file(safe)
            if found and found.is_file():
                return found
        cand_upload = (upload_dir / safe).resolve()
        if _is_within(cand_upload, upload_dir) and cand_upload.is_file():
            return cand_upload
        cand_media = (media_dir / safe).resolve()
        if _is_within(cand_media, media_dir) and cand_media.is_file():
            return cand_media
        cand_sample = (samples_dir / safe).resolve()
        if _is_within(cand_sample, samples_dir) and cand_sample.is_file():
            return cand_sample
        return None

    sanitized_frames: list[dict[str, Any]] = []
    referenced_media_names: set[str] = set()
    missing_files: list[str] = []

    for item in raw_frames:
        if not isinstance(item, dict):
            continue
        safe_fname = Path(str(item.get("filename") or "")).name
        if not safe_fname:
            continue

        src_path = _find_source(safe_fname)
        is_sample = bool(item.get("is_sample", False))
        if src_path is not None:
            if _is_within(src_path, samples_dir):
                is_sample = True
            else:
                _link_or_copy(src_path, media_dir / safe_fname)
                referenced_media_names.add(safe_fname)
        else:
            missing_files.append(safe_fname)

        pick_status = item.get("pickStatus")
        if pick_status not in ("pick", "reject"):
            pick_status = None

        frame_entry: dict[str, Any] = {
            "filename": safe_fname,
            "name": _clean_text(item.get("name"), 200, safe_fname),
            "is_raw": bool(item.get("is_raw", False)),
            "is_heif": bool(item.get("is_heif", False)),
            "is_sample": is_sample,
            "pickStatus": pick_status,
        }
        if isinstance(item.get("simRecipe"), dict):
            frame_entry["simRecipe"] = item["simRecipe"]
        if isinstance(item.get("negRecipe"), dict):
            frame_entry["negRecipe"] = item["negRecipe"]
        sanitized_frames.append(frame_entry)

    if not sanitized_frames:
        raise ProjectError("No se encontraron fotogramas válidos para guardar.")

    # Preserve optional flat-field calibration file if present
    neg_roll_raw = payload.get("negative_roll") if isinstance(payload.get("negative_roll"), dict) else {}
    flat_field_name = Path(str(neg_roll_raw.get("flat_field_file") or "")).name or None
    if flat_field_name:
        ff_src = _find_source(flat_field_name)
        if ff_src is not None and not _is_within(ff_src, samples_dir):
            _link_or_copy(ff_src, media_dir / flat_field_name)
            referenced_media_names.add(flat_field_name)
        elif ff_src is None:
            flat_field_name = None

    # Clean up orphaned media files from previous saves of this project
    if media_dir.is_dir():
        for existing_file in media_dir.iterdir():
            if existing_file.is_file() and existing_file.name not in referenced_media_names:
                try:
                    existing_file.unlink()
                except OSError:
                    pass

    active_idx = payload.get("active_frame_index", 0)
    try:
        active_idx = int(active_idx)
    except (TypeError, ValueError):
        active_idx = 0
    active_idx = max(0, min(active_idx, len(sanitized_frames) - 1))

    sheet_raw = payload.get("sheet") if isinstance(payload.get("sheet"), dict) else {}
    try:
        sheet_cols = int(sheet_raw.get("columns", 4))
    except (TypeError, ValueError):
        sheet_cols = 4
    sheet_cols = max(2, min(6, sheet_cols))

    export_raw = payload.get("export") if isinstance(payload.get("export"), dict) else {}
    view_mode = str(payload.get("view_mode") or "split")
    if view_mode not in ("split", "full", "original", "sheet"):
        view_mode = "split"

    manifest: dict[str, Any] = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "app_version": app_version,
        "id": pid,
        "name": name,
        "notes": notes,
        "created_at": existing_created_at or now_iso,
        "updated_at": now_iso,
        "app_mode": app_mode,
        "active_frame_index": active_idx,
        "view_mode": view_mode,
        "sheet": {
            "roll_name": _clean_text(sheet_raw.get("roll_name"), 120, ""),
            "columns": sheet_cols,
            "hide_rejected": bool(sheet_raw.get("hide_rejected", False)),
        },
        "export": {
            "output_format": _clean_text(export_raw.get("output_format"), 16, "jpg"),
            "easel_border": _clean_text(export_raw.get("easel_border"), 32, "none"),
            "dry_down_comp": float(export_raw.get("dry_down_comp", 0.0) or 0.0),
        },
        "analog_meta": payload.get("analog_meta") if isinstance(payload.get("analog_meta"), dict) else {},
        "negative_roll": {
            "roll_bounds": (
                neg_roll_raw.get("roll_bounds") if isinstance(neg_roll_raw.get("roll_bounds"), dict) else None
            ),
            "roll_frames_count": int(neg_roll_raw.get("roll_frames_count", 0) or 0),
            "flat_field_file": flat_field_name,
            "flat_field_label": _clean_text(neg_roll_raw.get("flat_field_label"), 120, ""),
            "flat_field_strength": float(neg_roll_raw.get("flat_field_strength", 1.0) or 1.0),
        },
        "frames": sanitized_frames,
    }

    _atomic_write_json(manifest_path, manifest)
    summary = _summarize_project(manifest, project_dir)
    return {
        "project": summary,
        "missing_files": missing_files,
    }


def load_project(
    projects_dir: Path,
    project_id: str,
    *,
    upload_dir: Path,
    samples_dir: Path,
) -> dict[str, Any]:
    """Load a saved roll project and ensure all its media files are ready in `upload_dir`."""
    pid = validate_project_id(project_id)
    project_dir = (projects_dir / pid).resolve()
    if not _is_within(project_dir, projects_dir) or not project_dir.is_dir():
        raise FileNotFoundError("Proyecto no encontrado.")

    manifest_path = project_dir / "project.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Archivo de proyecto no encontrado.")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProjectError(f"El archivo del proyecto está dañado: {exc}") from exc

    if not isinstance(data, dict):
        raise ProjectError("Formato de proyecto no válido.")

    media_dir = project_dir / "media"
    upload_dir.mkdir(parents=True, exist_ok=True)

    restored_frames: list[dict[str, Any]] = []
    missing_files: list[str] = []

    for frame in data.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        safe_fname = Path(str(frame.get("filename") or "")).name
        if not safe_fname:
            continue

        in_samples = (samples_dir / safe_fname).is_file()
        in_uploads = (upload_dir / safe_fname).is_file()
        in_media = (media_dir / safe_fname).is_file()

        if not in_samples and not in_uploads:
            if in_media:
                _link_or_copy(media_dir / safe_fname, upload_dir / safe_fname)
                in_uploads = True
            else:
                missing_files.append(safe_fname)
                continue

        frame_copy = dict(frame)
        frame_copy["filename"] = safe_fname
        frame_copy["thumb_url"] = f"/api/thumbnail/{safe_fname}"
        restored_frames.append(frame_copy)

    # Restore optional flat-field file if present
    neg_roll = data.get("negative_roll")
    if isinstance(neg_roll, dict) and neg_roll.get("flat_field_file"):
        ff_name = Path(str(neg_roll["flat_field_file"])).name
        if ff_name and not (upload_dir / ff_name).is_file() and (media_dir / ff_name).is_file():
            _link_or_copy(media_dir / ff_name, upload_dir / ff_name)

    data["frames"] = restored_frames
    if restored_frames:
        idx = int(data.get("active_frame_index", 0) or 0)
        data["active_frame_index"] = max(0, min(idx, len(restored_frames) - 1))
    else:
        data["active_frame_index"] = 0

    return {
        "project": data,
        "summary": _summarize_project(data, project_dir),
        "missing_files": missing_files,
    }


def rename_project(
    projects_dir: Path,
    project_id: str,
    new_name: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Rename a saved project and optionally update its notes."""
    pid = validate_project_id(project_id)
    project_dir = (projects_dir / pid).resolve()
    manifest_path = project_dir / "project.json"
    if not _is_within(project_dir, projects_dir) or not manifest_path.is_file():
        raise FileNotFoundError("Proyecto no encontrado.")

    cleaned_name = _clean_text(new_name, MAX_PROJECT_NAME_LEN)
    if not cleaned_name:
        raise ProjectError("El nombre del proyecto no puede estar vacío.")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["name"] = cleaned_name
    if notes is not None:
        data["notes"] = _clean_text(notes, MAX_PROJECT_NOTES_LEN, "")
    data["updated_at"] = _utc_now_iso()
    _atomic_write_json(manifest_path, data)
    return _summarize_project(data, project_dir)


def delete_project(projects_dir: Path, project_id: str) -> bool:
    """Permanently delete a saved project directory."""
    pid = validate_project_id(project_id)
    project_dir = (projects_dir / pid).resolve()
    if not _is_within(project_dir, projects_dir) or not project_dir.is_dir():
        return False
    shutil.rmtree(project_dir)
    return True


def _slugify_filename(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "").strip()).strip("._-")
    return (slug[:64] or "proyecto_haluro")


def export_project_archive(
    projects_dir: Path,
    project_id: str,
) -> tuple[io.BytesIO, str]:
    """Pack a saved roll project (`project.json` + `media/`) into a portable `.haluro` ZIP archive."""
    pid = validate_project_id(project_id)
    project_dir = (projects_dir / pid).resolve()
    manifest_path = project_dir / "project.json"
    if not _is_within(project_dir, projects_dir) or not manifest_path.is_file():
        raise FileNotFoundError("Proyecto no encontrado.")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    download_name = f"{_slugify_filename(data.get('name', pid))}.haluro"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(manifest_path, arcname="project.json")
        media_dir = project_dir / "media"
        if media_dir.is_dir():
            for item in sorted(media_dir.iterdir()):
                if item.is_file():
                    zf.write(item, arcname=f"media/{item.name}")

    buf.seek(0)
    return buf, download_name


def import_project_archive(
    projects_dir: Path,
    archive_stream: Any,
    *,
    allowed_media_exts: set[str],
    max_members: int = MAX_PROJECT_FRAMES + 20,
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    """Safely import a portable `.haluro` (ZIP) roll project into `projects_dir`."""
    try:
        zf = zipfile.ZipFile(archive_stream, mode="r")
    except zipfile.BadZipFile as exc:
        raise ProjectError("El archivo no es un paquete de proyecto .haluro válido.") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > max_members:
            raise ProjectError("El paquete de proyecto supera el límite máximo de archivos.")

        total_size = 0
        manifest_info = None
        media_infos: list[tuple[zipfile.ZipInfo, str]] = []

        for info in infos:
            if info.is_dir():
                continue
            # Reject symlinks in ZIP external attributes
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ProjectError("El paquete contiene enlaces simbólicos no permitidos.")

            parts = Path(info.filename).parts
            if not parts or any(p in ("..", "/", "\\") or p.startswith("/") for p in parts):
                raise ProjectError("Ruta insegura detectada dentro del archivo de proyecto.")

            total_size += info.file_size
            if total_size > max_uncompressed_bytes:
                raise ProjectError("El paquete de proyecto supera el tamaño máximo permitido.")

            if info.filename == "project.json":
                manifest_info = info
            elif len(parts) == 2 and parts[0] == "media":
                safe_name = Path(parts[1]).name
                if safe_name and Path(safe_name).suffix.lower() in allowed_media_exts:
                    media_infos.append((info, safe_name))

        if manifest_info is None:
            raise ProjectError("El paquete no contiene el archivo project.json.")

        try:
            raw_manifest = zf.read(manifest_info).decode("utf-8")
            data = json.loads(raw_manifest)
        except Exception as exc:
            raise ProjectError(f"No se pudo leer project.json: {exc}") from exc

        if not isinstance(data, dict) or not isinstance(data.get("frames"), list) or not data["frames"]:
            raise ProjectError("El proyecto importado no contiene fotogramas válidos.")
        if len(data["frames"]) > MAX_PROJECT_FRAMES:
            raise ProjectError(f"El proyecto supera el máximo de {MAX_PROJECT_FRAMES} fotogramas.")

        new_pid = _generate_project_id()
        projects_dir.mkdir(parents=True, exist_ok=True)
        project_dir = (projects_dir / new_pid).resolve()
        media_dir = project_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        try:
            for info, safe_name in media_infos:
                target = (media_dir / safe_name).resolve()
                if not _is_within(target, media_dir):
                    raise ProjectError("Ruta de medio fuera del proyecto.")
                with zf.open(info, "r") as src_f, open(target, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f, length=1024 * 1024)

            now_iso = _utc_now_iso()
            data["id"] = new_pid
            data["name"] = _clean_text(data.get("name"), MAX_PROJECT_NAME_LEN, "Proyecto importado")
            data["notes"] = _clean_text(data.get("notes"), MAX_PROJECT_NOTES_LEN, "")
            data["created_at"] = data.get("created_at") or now_iso
            data["updated_at"] = now_iso
            _atomic_write_json(project_dir / "project.json", data)
        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise

    return _summarize_project(data, project_dir)
