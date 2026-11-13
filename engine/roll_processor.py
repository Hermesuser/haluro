"""Procesamiento común de rollos para los modos simulation y negative.

Centraliza la lógica de revelado por lotes, generación de hojas de contacto y
guardado de archivos, compartida por:

* ``/api/develop_full`` y ``/api/negative/develop_full``
* ``/api/contact_sheet_preview`` y ``/api/negative/contact_sheet_preview``
* ``/api/save_contact_sheet`` y ``/api/negative/save_contact_sheet``
* El worker asíncrono ``/api/batch/develop_roll_start``

Antes de este módulo cada ruta duplicaba la iteración sobre ``per_frame_recipes``,
la validación de frames, el guardado de imágenes y la composición de la hoja de
contacto. Ahora toda esa lógica vive aquí y las rutas de Flask son capas finas.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from app import (
    DEVELOPED_DIR,
    MAX_BATCH_FRAMES,
    MAX_FULL_RES_WORKERS,
    _canonical_film_key,
    _canonical_profile_key,
    _parse_analog_meta,
    _resolve_sheet_meta,
    _resolve_source_file,
)
from engine.contact_sheet import generate_contact_sheet
from engine.negative_inverter import MINILAB_PROFILES
from engine.pipeline import get_srgb_icc_bytes, save_output_image


class RollJobError(RuntimeError):
    """Error durante el procesamiento de un rollo."""


def _frame_name(item: object) -> str | None:
    """Extrae un nombre de archivo limpio de un elemento de la lista de frames."""
    if not isinstance(item, str):
        return None
    name = Path(item).name
    return name or None


def _bounded(filenames: object) -> list[str]:
    """Normaliza y acota la lista de frames de una petición de lote."""
    frames: list[str] = []
    for item in filenames or []:
        name = _frame_name(item)
        if name:
            frames.append(name)
        if len(frames) >= MAX_BATCH_FRAMES:
            break
    return frames


def resolve_output_extension(fmt_str: str | None) -> str:
    """Devuelve la extensión de salida canónica (incluye el punto)."""
    from app import ALLOWED_OUTPUT_EXTS as _exts  # import local para evitar ciclo

    fmt = str(fmt_str or "jpg").lower().lstrip(".")
    return _exts.get(fmt, ".jpg")


def roll_output_dir(roll_name: str, key: str, mode: str) -> Path:
    """Devuelve el directorio de salida para un rollo."""
    suffix = f"_neg_{key}" if mode == "negative" else f"_{key}"
    return DEVELOPED_DIR / f"{roll_name}{suffix}"


def render_frame_thumbnail(
    fname: str,
    mode: str,
    common_params: dict,
    per_frame_recipes: dict | None,
    max_dim: int,
) -> Image.Image | None:
    """Render una miniatura de un frame para contacto o preview."""
    fpath = _resolve_source_file(fname)
    if not fpath:
        return None

    fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None

    if mode == "negative":
        from engine.negative_inverter import process_negative_to_image

        frame_params = (
            {**common_params, **fr} if isinstance(fr, dict) else common_params
        )
        # process_negative_to_image espera los parámetros en su forma original.
        return process_negative_to_image(
            fpath,
            max_dim=max_dim,
            return_float=False,
            **frame_params,
        )

    # modo simulation
    from engine.pipeline import develop_frame

    def _frame_val(key: str, default) -> object:
        return fr.get(key, default) if isinstance(fr, dict) else default

    film_key = _canonical_film_key(_frame_val("film", common_params.get("film", "portra400")))
    return develop_frame(
        fpath,
        film_key=film_key,
        ev_adjust=_frame_val("ev", common_params.get("ev", 0.0)),
        halation_mult=_frame_val("halation", common_params.get("halation", 1.0)),
        grain_mult=_frame_val("grain", common_params.get("grain", 1.0)),
        vignette_mult=_frame_val("vignette", common_params.get("vignette", 1.0)),
        shadows=_frame_val("shadows", common_params.get("shadows", 0.0)),
        mids=_frame_val("mids", common_params.get("mids", 0.0)),
        highlights=_frame_val("highlights", common_params.get("highlights", 0.0)),
        add_date=bool(_frame_val("date", common_params.get("add_date", False))),
        max_dim=max_dim,
        rotate=int(_frame_val("rotate", common_params.get("rotate", 0))),
        flip_h=bool(_frame_val("flip_h", common_params.get("flip_h", False))),
    )


def develop_one_full_res(
    fname: str,
    mode: str,
    common_params: dict,
    per_frame_recipes: dict | None,
    out_ext: str,
    target_dir: Path,
    analog_meta: dict,
) -> tuple[str, str, Image.Image] | None:
    """Desarrolla un frame a resolución completa y lo guarda en disco.

    Devuelve ``(nombre_original, nombre_salida, imagen_PIL)`` o ``None`` si
    el archivo de origen no se encuentra.
    """
    fpath = _resolve_source_file(fname)
    if not fpath:
        return None

    fr = per_frame_recipes.get(fname) if isinstance(per_frame_recipes, dict) else None

    if mode == "negative":
        from engine.negative_inverter import process_negative_to_image

        frame_params = (
            {**common_params, **fr} if isinstance(fr, dict) else common_params
        )
        prof_key = _canonical_profile_key(frame_params.get("profile_key", "frontier"))
        pos_img, srgb_f = process_negative_to_image(
            fpath,
            max_dim=None,
            return_float=True,
            **frame_params,
        )
        out_name = f"{fpath.stem}_positive_{prof_key}{out_ext}"
    else:
        from engine.pipeline import develop_frame

        film_key = (
            _canonical_film_key(fr.get("film", common_params.get("film", "portra400")))
            if isinstance(fr, dict)
            else common_params.get("film", "portra400")
        )

        def _frame_val(key: str, default) -> object:
            return fr.get(key, default) if isinstance(fr, dict) else default

        dev_img, srgb_f = develop_frame(
            fpath,
            film_key=film_key,
            ev_adjust=_frame_val("ev", common_params.get("ev", 0.0)),
            halation_mult=_frame_val("halation", common_params.get("halation", 1.0)),
            grain_mult=_frame_val("grain", common_params.get("grain", 1.0)),
            vignette_mult=_frame_val("vignette", common_params.get("vignette", 1.0)),
            shadows=_frame_val("shadows", common_params.get("shadows", 0.0)),
            mids=_frame_val("mids", common_params.get("mids", 0.0)),
            highlights=_frame_val("highlights", common_params.get("highlights", 0.0)),
            add_date=bool(_frame_val("date", common_params.get("add_date", False))),
            max_dim=None,
            rotate=int(_frame_val("rotate", common_params.get("rotate", 0))),
            flip_h=bool(_frame_val("flip_h", common_params.get("flip_h", False))),
            return_float=True,
        )
        pos_img = dev_img
        out_name = f"{fpath.stem}_{film_key}{out_ext}"
        srgb_f = srgb_f
        prof_key = film_key

    target_path = target_dir / out_name
    save_output_image(
        pos_img,
        target_path,
        source_path=fpath,
        quality=96,
        float_srgb=srgb_f,
        analog_meta=analog_meta,
    )
    return (fpath.name, out_name, pos_img)


def build_contact_sheet(
    images: list[Image.Image],
    roll_name: str,
    film_name: str,
    columns: int,
    frame_labels: list[str],
    thumb_width: int = 480,
    return_layout: bool = False,
    quality: int = 93,
    save_path: Path | None = None,
) -> Image.Image | tuple[Image.Image, list[dict]]:
    """Genera una hoja de contacto y opcionalmente la guarda en disco."""
    sheet, layout_boxes = generate_contact_sheet(
        images,
        roll_name=roll_name,
        film_name=film_name,
        columns=columns,
        thumb_width=thumb_width,
        return_layout=True,
        frame_labels=frame_labels,
    )

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(
            save_path,
            format="JPEG",
            quality=quality,
            subsampling=0,
            icc_profile=get_srgb_icc_bytes(),
        )

    if return_layout:
        return sheet, layout_boxes
    return sheet


def resolve_sheet_meta(
    valid_filenames: list[str],
    per_frame_recipes: dict | None,
    mode: str,
    fallback_key: str,
    fallback_name: str,
) -> tuple[str, list[str]]:
    """Calcula la etiqueta de la hoja y las etiquetas de frame."""
    return _resolve_sheet_meta(
        valid_filenames,
        per_frame_recipes if isinstance(per_frame_recipes, dict) else {},
        mode,
        fallback_key,
        fallback_name,
    )


class RollBatchJob:
    """Gestiona un trabajo asíncrono de revelado de rollo con progreso y cancelación."""

    def __init__(self, job_id: str, data: dict):
        self.job_id = job_id
        self.data = data
        self.status = "running"
        self.total = 0
        self.completed = 0
        self.percent = 2
        self.current_file = "Preparando cámara oscura…"
        self.elapsed_seconds = 0.0
        self.result: dict | None = None
        self.error: str | None = None
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._t_start = time.time()

    def update(self, **kwargs) -> None:
        with self._lock:
            self.__dict__.update(kwargs)

    def payload(self) -> dict:
        with self._lock:
            return {k: v for k, v in self.__dict__.items() if k not in ("cancel_event", "_lock", "_t_start")}

    def run(self) -> None:
        """Ejecuta el revelado del rollo en segundo plano."""
        data = self.data
        try:
            mode = data.get("app_mode", "simulation")
            filenames = _bounded(data.get("filenames", []))
            self.total = len(filenames)
            if not filenames:
                self.update(status="error", error="No hay fotogramas para procesar")
                return

            gen_sheet = bool(data.get("sheet", True))
            out_ext = resolve_output_extension(data.get("format", "jpg"))
            raw_roll_name = str(data.get("roll_name", "HALURO ROLL")).strip()[:40] or "HALURO ROLL"
            roll_name = _canonical_profile_key(raw_roll_name) if mode == "negative" else raw_roll_name
            roll_name = roll_name or ("HALURO_ROLL" if mode == "negative" else "HALURO_ROLL")
            columns = int(data.get("columns", 4) or 4)
            analog_meta = _parse_analog_meta(data)
            per_frame_recipes = data.get("per_frame_recipes") or {}
            is_neg = mode == "negative"

            if is_neg:
                from engine.negative_inverter import process_negative_to_image  # noqa: F401

                common_params = dict(data)
                profile_key = _canonical_profile_key(common_params.get("profile", "frontier"))
                profile_info = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])
                roll_folder = f"{roll_name}_neg_{profile_key}"
                sheet_film_name = f"Negativo · {profile_info['name']}"
                fallback_key = profile_key
            else:
                from engine.films import get_film as _get_film

                common_params = dict(data)
                film_key = _canonical_film_key(common_params.get("film", "portra400"))
                film_info = _get_film(film_key)
                roll_folder = f"{roll_name}_{film_key}"
                sheet_film_name = film_info["name"]
                fallback_key = film_key

            target_dir = roll_output_dir(roll_name, fallback_key, mode)
            target_dir.mkdir(parents=True, exist_ok=True)

            indexed_results: dict[int, tuple[str, Image.Image]] = {}
            completed_count = 0
            progress_lock = threading.Lock()

            def _worker_task(idx_and_name: tuple[int, str]) -> tuple[int, str, str, Image.Image] | None:
                idx, fname = idx_and_name
                if self.cancel_event.is_set():
                    return None
                res = develop_one_full_res(
                    fname,
                    mode,
                    common_params,
                    per_frame_recipes,
                    out_ext,
                    target_dir,
                    analog_meta,
                )
                if self.cancel_event.is_set():
                    return None
                if res:
                    src_name, out_name, img = res
                    return (idx, src_name, out_name, img)
                return None

            max_workers = min(MAX_FULL_RES_WORKERS, max(1, os.cpu_count() or 1))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_worker_task, (i, fn)) for i, fn in enumerate(filenames)]
                for fut in as_completed(futures):
                    if self.cancel_event.is_set():
                        for pending_f in futures:
                            pending_f.cancel()
                        self.update(
                            status="cancelled",
                            current_file="Proceso cancelado por el usuario.",
                            elapsed_seconds=round(time.time() - self._t_start, 1),
                        )
                        return

                    res = fut.result()
                    if res:
                        idx, src_name, out_name, img = res
                        indexed_results[idx] = (out_name, img)
                        with progress_lock:
                            completed_count += 1
                            pct = int(round((completed_count / max(1, self.total)) * 90))
                            self.update(
                                completed=completed_count,
                                percent=pct,
                                current_file=src_name,
                                elapsed_seconds=round(time.time() - self._t_start, 1),
                            )

            if self.cancel_event.is_set():
                self.update(
                    status="cancelled",
                    current_file="Proceso cancelado por el usuario.",
                    elapsed_seconds=round(time.time() - self._t_start, 1),
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
                self.update(
                    percent=94,
                    current_file="Componiendo hoja de contactos de archivo…",
                    elapsed_seconds=round(time.time() - self._t_start, 1),
                )
                batch_sheet_film, frame_labels = resolve_sheet_meta(
                    valid_filenames,
                    per_frame_recipes,
                    mode,
                    fallback_key,
                    sheet_film_name,
                )
                sheet_path = target_dir / "SHEET.jpg"
                build_contact_sheet(
                    developed_images,
                    roll_name=raw_roll_name,
                    film_name=batch_sheet_film,
                    columns=columns,
                    frame_labels=frame_labels,
                    save_path=sheet_path,
                )
                output_files.append("SHEET.jpg")
                sheet_created = True

            elapsed = round(time.time() - self._t_start, 2)
            self.update(
                status="completed",
                completed=len(developed_images),
                percent=100,
                current_file="¡Rollo completado!",
                elapsed_seconds=elapsed,
                result={
                    "success": True,
                    "roll_dir": str(target_dir),
                    "roll_folder": roll_folder,
                    "files": output_files,
                    "sheet": sheet_created,
                    "total_frames": len(developed_images),
                    "elapsed_seconds": elapsed,
                },
            )
        except Exception as exc:  # noqa: BLE001 - captura todo para reportar estado de error
            import logging

            logger = logging.getLogger("haluro.roll_processor")
            logger.exception("Batch roll job failed: %s", exc)
            self.update(
                status="error",
                error=str(exc),
                elapsed_seconds=round(time.time() - self._t_start, 1),
            )
