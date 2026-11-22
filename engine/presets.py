"""Persistent user recipe presets library for Haluro — Laboratorio Analógico Digital.

Allows photographers to save, list, apply, delete, export, and import named
film emulation and negative inversion recipes across rolls and sessions.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_PRESETS = 200
MAX_PRESET_NAME_LEN = 100
MAX_PRESET_NOTES_LEN = 300
_PRESET_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{4,80}$")


class PresetError(ValueError):
    """Raised when a preset operation receives invalid input."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_text(val: Any, max_len: int, default: str = "") -> str:
    s = str(val or "").strip()
    return s[:max_len] if s else default


def _presets_path(data_root: Path) -> Path:
    return (data_root / "presets.json").resolve()


def _atomic_write(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": 1, "presets": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_presets(data_root: Path) -> list[dict[str, Any]]:
    """Return all saved user presets sorted by `updated_at` descending."""
    path = _presets_path(data_root)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("presets") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        valid = [p for p in items if isinstance(p, dict) and p.get("id") and isinstance(p.get("recipe"), dict)]
        valid.sort(key=lambda p: p.get("updated_at") or p.get("created_at") or "", reverse=True)
        return valid
    except Exception:
        return []


def save_preset(
    data_root: Path,
    *,
    name: str,
    mode: str,
    recipe: dict[str, Any],
    notes: str = "",
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a named user recipe preset."""
    cleaned_name = _clean_text(name, MAX_PRESET_NAME_LEN)
    if not cleaned_name:
        raise PresetError("El nombre del preset no puede estar vacío.")
    norm_mode = "negative" if mode == "negative" else "simulation"
    if not isinstance(recipe, dict) or not recipe:
        raise PresetError("La receta del preset no es válida.")

    items = list_presets(data_root)
    now_iso = _utc_now_iso()

    if preset_id:
        pid = str(preset_id).strip()
        if not _PRESET_ID_RE.match(pid):
            raise PresetError("Identificador de preset no válido.")
    else:
        pid = f"preset_{uuid.uuid4().hex[:10]}"

    existing_idx = next((i for i, p in enumerate(items) if p.get("id") == pid), None)
    if existing_idx is None and len(items) >= MAX_PRESETS:
        raise PresetError(f"Has alcanzado el límite máximo de {MAX_PRESETS} presets guardados.")

    entry = {
        "id": pid,
        "name": cleaned_name,
        "mode": norm_mode,
        "notes": _clean_text(notes, MAX_PRESET_NOTES_LEN, ""),
        "recipe": recipe,
        "created_at": items[existing_idx].get("created_at", now_iso) if existing_idx is not None else now_iso,
        "updated_at": now_iso,
    }
    if existing_idx is not None:
        items[existing_idx] = entry
    else:
        items.insert(0, entry)

    _atomic_write(_presets_path(data_root), items)
    return entry


def delete_preset(data_root: Path, preset_id: str) -> bool:
    """Delete a saved preset by ID."""
    pid = str(preset_id or "").strip()
    if not _PRESET_ID_RE.match(pid):
        raise PresetError("Identificador de preset no válido.")
    items = list_presets(data_root)
    kept = [p for p in items if p.get("id") != pid]
    if len(kept) == len(items):
        return False
    _atomic_write(_presets_path(data_root), kept)
    return True


def import_presets_payload(data_root: Path, raw_data: Any) -> int:
    """Import presets from a parsed JSON object or list, assigning fresh IDs."""
    if isinstance(raw_data, dict):
        incoming = raw_data.get("presets")
    elif isinstance(raw_data, list):
        incoming = raw_data
    else:
        incoming = None

    if not isinstance(incoming, list) or not incoming:
        raise PresetError("El archivo JSON no contiene presets válidos.")

    items = list_presets(data_root)
    now_iso = _utc_now_iso()
    added = 0
    for item in incoming:
        if len(items) >= MAX_PRESETS:
            break
        if not isinstance(item, dict) or not isinstance(item.get("recipe"), dict):
            continue
        name = _clean_text(item.get("name"), MAX_PRESET_NAME_LEN)
        if not name:
            continue
        mode = "negative" if item.get("mode") == "negative" else "simulation"
        items.insert(
            0,
            {
                "id": f"preset_{uuid.uuid4().hex[:10]}",
                "name": name,
                "mode": mode,
                "notes": _clean_text(item.get("notes"), MAX_PRESET_NOTES_LEN, ""),
                "recipe": item["recipe"],
                "created_at": item.get("created_at") or now_iso,
                "updated_at": now_iso,
            },
        )
        added += 1

    if added == 0:
        raise PresetError("No se encontraron presets válidos para importar.")
    _atomic_write(_presets_path(data_root), items)
    return added
