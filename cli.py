#!/usr/bin/env python3
"""Haluro CLI: emulación de 72 películas químicas e inversión óptica de negativos desde terminal."""

import argparse
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from engine import APP_NAME, __version__, about_payload
from engine.contact_sheet import generate_contact_sheet
from engine.films import VALID_GRAIN_ASAS, get_film, list_films
from engine.negative_inverter import (
    BW_TONING_PROFILES,
    MINILAB_PROFILES,
    PRINT_FINISHES,
    SCAN_SOURCES,
    process_negative_to_image,
)
from engine.pipeline import develop_frame, save_output_image

VALID_INPUT_EXTS = {
    ".cr2", ".cr3", ".dng", ".nef", ".arw", ".orf", ".rw2", ".raf", ".pef",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif",
}
FORMAT_EXT_MAP = {"jpg": ".jpg", "png": ".png", "tiff": ".tiff"}


def _collect_inputs(in_path: Path):
    if in_path.is_file():
        return [in_path]
    if in_path.is_dir():
        return sorted([p for p in in_path.iterdir() if p.suffix.lower() in VALID_INPUT_EXTS])
    print(f"Error: ruta no encontrada -> {in_path}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Haluro CLI — Laboratorio Analógico Digital (Emulación & Revelado de Negativos)"
    )
    parser.add_argument("-v", "--version", action="version", version=f"{APP_NAME} v{__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # about
    subparsers.add_parser("about", help="Mostrar información de la app, autor y licencias")

    # list films
    list_p = subparsers.add_parser("list", help="Listar las 72 películas analógicas disponibles")
    list_p.add_argument(
        "--category",
        choices=["neg", "slide", "cine", "bw", "xpro", "print"],
        help="Filtrar por proceso químico",
    )

    # develop (emulation)
    dev_p = subparsers.add_parser("develop", help="Emular película analógica sobre fotos RAW/digitales")
    dev_p.add_argument("input", help="Archivo RAW/imagen o carpeta")
    dev_p.add_argument("--film", default="portra400", help="Clave de película (por defecto: portra400)")
    dev_p.add_argument("--out", default="./developed", help="Carpeta de salida (por defecto: ./developed)")
    dev_p.add_argument("--format", choices=["jpg", "png", "tiff"], default="jpg", help="Formato maestro")
    dev_p.add_argument("--ev", type=float, default=0.0, help="Compensación de exposición en EV")
    dev_p.add_argument("--halation", type=float, default=1.0, help="Multiplicador de halación")
    dev_p.add_argument("--grain", type=float, default=1.0, help="Multiplicador de grano de plata")
    dev_p.add_argument(
        "--grain-asa",
        choices=list(VALID_GRAIN_ASAS),
        default="auto",
        help="ASA/ISO del rollo para perfilar el tamaño y densidad del grano (auto, 100..6400)",
    )
    dev_p.add_argument("--vignette", type=float, default=1.0, help="Multiplicador de viñeteo")
    dev_p.add_argument("--date", action="store_true", help="Estampar fecha en cuarzo ámbar")
    dev_p.add_argument("--sheet", action="store_true", help="Generar hoja de contactos SHEET.jpg")
    dev_p.add_argument("--max-dim", type=int, default=None, help="Escalar lado mayor opcionalmente")
    dev_p.add_argument("--camera", default="", help="Modelo de cámara analógica para EXIF")
    dev_p.add_argument("--lens", default="", help="Objetivo analógico para EXIF")
    dev_p.add_argument("--film-stock", default="", help="Película disparada para EXIF")
    dev_p.add_argument("--iso", default="", help="ISO expuesto para EXIF")

    # invert (negative lab)
    inv_p = subparsers.add_parser("invert", help="Revelar negativos escaneados C-41 o Blanco y Negro")
    inv_p.add_argument("input", help="Archivo o carpeta de negativos escaneados")
    inv_p.add_argument(
        "--profile",
        choices=list(MINILAB_PROFILES.keys()),
        default="frontier",
        help="Perfil fotoquímico o escáner (ra4_paper, cine_ecp, frontier, noritsu, pakon, vlog_flat, linear, bw)",
    )
    inv_p.add_argument("--type", choices=["color", "bw"], default="color", help="Proceso (color C-41 o bw)")
    inv_p.add_argument(
        "--light-source",
        choices=["standard", "cool", "warm"],
        default="standard",
        help="Espectro del backlight (standard CRI 6000-9000K, cool >9000K, warm <5500K)",
    )
    inv_p.add_argument(
        "--tone",
        choices=["soft", "standard", "vivid", "highlight_soft", "shadow_soft"],
        default="standard",
        help="Carácter tonal del revelado (soft, standard, vivid, highlight_soft, shadow_soft)",
    )
    inv_p.add_argument(
        "--scan-source",
        choices=list(SCAN_SOURCES.keys()),
        default="camera_raw",
        help="Origen de digitalización (camera_raw, scanner_raw, flatbed_tiff)",
    )
    inv_p.add_argument("--pre-sat", type=float, default=1.0, help="Pre-saturación óptica de tintes (0.5 a 1.6)")
    inv_p.add_argument(
        "--print-finish",
        choices=list(PRINT_FINISHES.keys()),
        default="none",
        help="Acabado de copia posterior (none, crystal_archive, portra_airy, gold_warm, etc.)",
    )
    inv_p.add_argument("--finish-amount", type=float, default=1.0, help="Intensidad del acabado (0.0 a 2.0)")
    inv_p.add_argument(
        "--bw-toner",
        choices=list(BW_TONING_PROFILES.keys()),
        default="neutral",
        help="Virado químico B&N o papel fine-art (selenium_2, palladium, sepia_sulfide, etc.)",
    )

    # render-project (.haluro portable archive or local project folder)
    proj_p = subparsers.add_parser(
        "render-project",
        help="Revelar todos los fotogramas de un proyecto guardado (.haluro o carpeta de proyecto)",
    )
    proj_p.add_argument("project", help="Ruta al archivo .haluro o carpeta que contiene project.json")
    proj_p.add_argument("--out", default="./project_render", help="Carpeta de salida")
    proj_p.add_argument("--format", choices=["jpg", "png", "tiff"], default=None, help="Sobrescribir formato")
    proj_p.add_argument("--only-picked", action="store_true", help="Revelar solo fotogramas marcados como elegidos")
    proj_p.add_argument("--max-dim", type=int, default=None, help="Escalar lado mayor opcionalmente (ej. 2048)")
    proj_p.add_argument("--quality", type=int, default=96, help="Calidad JPEG (60-100)")
    proj_p.add_argument("--sheet", action="store_true", help="Generar también hoja de contactos SHEET.jpg")
    inv_p.add_argument(
        "--sharpen",
        choices=["off", "lab", "scanner"],
        default="off",
        help="Nitidez óptica en luminancia con protección de grano (off, lab, scanner)",
    )
    inv_p.add_argument("--camera", default="", help="Modelo de cámara analógica para EXIF")
    inv_p.add_argument("--lens", default="", help="Objetivo analógico para EXIF")
    inv_p.add_argument("--film-stock", default="", help="Película original disparada para EXIF")
    inv_p.add_argument("--iso", default="", help="ISO disparado para EXIF")
    inv_p.add_argument("--out", default="./developed", help="Carpeta de salida")
    inv_p.add_argument(
        "--format",
        choices=["jpg", "png", "tiff"],
        default="jpg",
        help="Formato maestro (tiff = 16-bit)",
    )
    inv_p.add_argument("--brightness", type=float, default=0.0, help="Ajuste de brillo (-1.0 a 1.0)")
    inv_p.add_argument("--midtone-nd", type=float, default=0.0, help="Densidad neutra en medios tonos (-1.0 a 1.0)")
    inv_p.add_argument("--contrast", type=float, default=0.0, help="Ajuste de contraste (-1.0 a 1.0)")
    inv_p.add_argument("--push-pull", type=float, default=0.0, help="Latitud Pull/Push (-1.0 a 1.0)")
    inv_p.add_argument("--inky-blacks", type=float, default=0.0, help="Negros anti-velo (0.0 a 1.0)")
    inv_p.add_argument("--rp-tone", type=float, default=0.0, help="Vibrancia analógica RP Tone (0.0 a 1.0)")
    inv_p.add_argument("--crop", type=float, default=0.0, help="Recorte limpio de bordes (0.0 a 0.15)")
    inv_p.add_argument("--sheet", action="store_true", help="Generar hoja de contactos positiva")

    args = parser.parse_args()

    if args.command == "about":
        info = about_payload()
        print("\n" + "=" * 68)
        print(f"  {info['full_name']} (v{info['version']})")
        print(f"  {info['tagline']}")
        print("=" * 68)
        dev = info["developer"]
        print(f"\n  Desarrollador:  {dev['name']} ({dev['role']})")
        print(f"  Estudio / País: {dev['studio']} · {dev['country']}")
        print(f"  Licencia:       {info['license']} (Código abierto y distribución gratuita)")
        print(f"  Copyright:      {info['copyright']}")
        print(f"\n  Privacidad:\n    {info['privacy_notice']}")
        print(f"\n  Aviso de marcas registradas:\n    {info['trademark_notice']}")
        print("\n  Componentes y licencias de terceros:")
        for tp in info["third_party"]:
            print(f"    • {tp['component']}: {tp['author']} ({tp['license']})")
        print("=" * 68 + "\n")
        return

    if args.command == "list":
        films = list_films()
        if args.category:
            films = [f for f in films if f["kind"] == args.category]
        print(f"\n  {'CLAVE':<16} {'MARCA':<12} {'PELÍCULA':<28} {'ISO':<6} {'PROCESO'}")
        print("─" * 80)
        for f in films:
            print(f"  {f['key']:<16} {f['brand']:<12} {f['name']:<28} {f['iso']:<6} {f['category']}")
        print(f"\n  Total: {len(films)} emulsiones disponibles en Haluro.\n")
        return

    if args.command == "render-project":
        _run_render_project(args)
        return

    in_path = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = _collect_inputs(in_path)
    if not files:
        print("No se encontraron archivos compatibles.")
        sys.exit(1)

    ext = FORMAT_EXT_MAP[args.format]

    if args.command == "develop":
        film_info = get_film(args.film)
        print(f"\n  Haluro · Revelando {len(files)} fotograma(s) con {film_info['name']} (ISO {film_info['iso']})…\n")
        developed_images = []
        t_start = time.time()

        dev_analog_meta = {
            "camera_model": args.camera,
            "lens": args.lens,
            "film_stock": args.film_stock or film_info["name"],
            "shot_iso": args.iso,
        }
        has_analog_meta = bool(args.camera or args.lens or args.film_stock or args.iso)
        dev_analog_meta = {k: v for k, v in dev_analog_meta.items() if v} if has_analog_meta else {}

        for idx, file_p in enumerate(files, 1):
            t0 = time.time()
            out_file = out_dir / f"{file_p.stem}_{args.film}{ext}"
            print(f"  [{idx}/{len(files)}] {file_p.name} -> {out_file.name}…", end="", flush=True)
            img, srgb_f = develop_frame(
                file_p,
                film_key=args.film,
                ev_adjust=args.ev,
                halation_mult=args.halation,
                grain_mult=args.grain,
                grain_asa=args.grain_asa,
                vignette_mult=args.vignette,
                add_date=args.date,
                max_dim=args.max_dim,
                return_float=True,
            )
            save_output_image(
                img,
                out_file,
                source_path=file_p,
                quality=96,
                float_srgb=srgb_f,
                analog_meta=dev_analog_meta or None,
            )
            developed_images.append(img)
            print(f" listo ({time.time() - t0:.2f}s)")

        if args.sheet and developed_images:
            sheet_path = out_dir / f"SHEET_{args.film}.jpg"
            sheet = generate_contact_sheet(
                developed_images, roll_name=in_path.stem.upper(), film_name=film_info["name"]
            )
            sheet.save(sheet_path, quality=93, subsampling=0)
            print(f"\n  Hoja de contactos creada: {sheet_path}")

        print(f"\n  Completado en {time.time() - t_start:.2f}s · Carpeta: {out_dir.resolve()}\n")
        return

    if args.command == "invert":
        prof = MINILAB_PROFILES[args.profile]
        print(f"\n  Haluro · Invirtiendo {len(files)} negativo(s) con perfil {prof['name']}…\n")
        developed_images = []
        t_start = time.time()

        analog_meta = {
            "camera_model": args.camera,
            "lens": args.lens,
            "film_stock": args.film_stock,
            "shot_iso": args.iso,
        }
        analog_meta = {k: v for k, v in analog_meta.items() if v}

        for idx, file_p in enumerate(files, 1):
            t0 = time.time()
            out_file = out_dir / f"{file_p.stem}_positive_{args.profile}{ext}"
            print(f"  [{idx}/{len(files)}] {file_p.name} -> {out_file.name}…", end="", flush=True)
            img, srgb_f = process_negative_to_image(
                file_p,
                film_type=args.type,
                profile_key=args.profile,
                light_source=args.light_source,
                scan_source=args.scan_source,
                pre_saturation=args.pre_sat,
                tone_variant=args.tone,
                print_finish=args.print_finish,
                finish_amount=args.finish_amount,
                bw_toner=args.bw_toner,
                sharpen_mode=args.sharpen,
                brightness=args.brightness,
                midtone_nd=args.midtone_nd,
                contrast=args.contrast,
                push_pull=args.push_pull,
                inky_blacks=args.inky_blacks,
                rp_tone=args.rp_tone,
                crop_pct=args.crop,
                max_dim=None,
                return_float=True,
            )
            save_output_image(
                img,
                out_file,
                source_path=file_p,
                quality=96,
                float_srgb=srgb_f,
                analog_meta=analog_meta or None,
            )
            developed_images.append(img)
            print(f" listo ({time.time() - t0:.2f}s)")

        if args.sheet and developed_images:
            sheet_path = out_dir / f"SHEET_positive_{args.profile}.jpg"
            sheet = generate_contact_sheet(
                developed_images,
                roll_name=in_path.stem.upper(),
                film_name=f"Negativo · {prof['name']}",
            )
            sheet.save(sheet_path, quality=93, subsampling=0)
            print(f"\n  Hoja de contactos positiva creada: {sheet_path}")

        print(f"\n  Completado en {time.time() - t_start:.2f}s · Carpeta: {out_dir.resolve()}\n")


def _run_render_project(args) -> None:
    proj_path = Path(args.project).expanduser().resolve()
    if not proj_path.exists():
        print(f"Error: proyecto no encontrado -> {proj_path}")
        sys.exit(1)

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    with tempfile.TemporaryDirectory(prefix="haluro_cli_proj_") as tmp_str:
        work_dir = Path(tmp_str)
        if proj_path.is_file() and zipfile.is_zipfile(proj_path):
            with zipfile.ZipFile(proj_path, "r") as zf:
                for info in zf.infolist():
                    parts = Path(info.filename).parts
                    if not parts or any(p in ("..", "/", "\\") or p.startswith("/") for p in parts):
                        continue
                    zf.extract(info, work_dir)
            manifest_file = work_dir / "project.json"
            media_dir = work_dir / "media"
        else:
            manifest_file = proj_path / "project.json" if proj_path.is_dir() else proj_path
            media_dir = manifest_file.parent / "media"

        if not manifest_file.is_file():
            print(f"Error: project.json no encontrado en {proj_path}")
            sys.exit(1)

        proj_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        frames = proj_data.get("frames") or []
        if args.only_picked:
            frames = [f for f in frames if f.get("pickStatus") == "pick"]
        if not frames:
            print("No hay fotogramas para revelar en este proyecto.")
            return

        exp_cfg = proj_data.get("export") or {}
        fmt = args.format or exp_cfg.get("output_format") or "jpg"
        ext = FORMAT_EXT_MAP.get(fmt, ".jpg")
        easel_border = exp_cfg.get("easel_border", "none")
        dry_down = float(exp_cfg.get("dry_down_comp", 0.0) or 0.0)
        analog_meta = proj_data.get("analog_meta") or None
        app_mode = proj_data.get("app_mode", "simulation")

        print(f"\nHaluro — Renderizando proyecto «{proj_data.get('name', proj_path.stem)}» ({len(frames)} fotos)")
        developed_images = []
        for idx, frame in enumerate(frames, 1):
            fname = Path(str(frame.get("filename") or "")).name
            src = media_dir / fname
            if not src.is_file():
                print(f"  [{idx}/{len(frames)}] {fname} — omitido (archivo no encontrado)")
                continue
            t0 = time.time()
            if app_mode == "negative":
                rec = frame.get("negRecipe") or {}
                prof = str(rec.get("profile") or "frontier")
                out_file = out_dir / f"{idx:02d}_{src.stem}_{prof}{ext}"
                img, srgb_f = process_negative_to_image(
                    src,
                    film_type=str(rec.get("film_type") or "color"),
                    profile_key=prof,
                    brightness=float(rec.get("brightness", 0.0) or 0.0),
                    contrast=float(rec.get("contrast", 0.0) or 0.0),
                    max_dim=None,
                    return_float=True,
                )
            else:
                rec = frame.get("simRecipe") or {}
                fkey = str(rec.get("film") or "portra400")
                out_file = out_dir / f"{idx:02d}_{src.stem}_{fkey}{ext}"
                img, srgb_f = develop_frame(
                    src,
                    film_key=fkey,
                    ev_adjust=float(rec.get("ev", 0.0) or 0.0),
                    halation_mult=float(rec.get("halation", 1.0) if rec.get("halation") is not None else 1.0),
                    grain_mult=float(rec.get("grain", 1.0) if rec.get("grain") is not None else 1.0),
                    grain_asa=str(rec.get("grain_asa") or "auto"),
                    vignette_mult=float(rec.get("vignette", 1.0) if rec.get("vignette") is not None else 1.0),
                    shadows=float(rec.get("shadows", 0.0) or 0.0),
                    mids=float(rec.get("mids", 0.0) or 0.0),
                    highlights=float(rec.get("highlights", 0.0) or 0.0),
                    curve=rec.get("curve"),
                    add_date=bool(rec.get("date", False)),
                    dev_process=str(rec.get("dev_process") or "standard"),
                    film_strength=float(
                        1.0 if rec.get("film_strength") is None else rec.get("film_strength")
                    ),
                    sim_temp=float(rec.get("sim_temp", 0.0) or 0.0),
                    sim_tint=float(rec.get("sim_tint", 0.0) or 0.0),
                    bw_filter=str(rec.get("bw_filter") or "none"),
                    zone_dev=str(rec.get("zone_dev") or "N"),
                    enlarger_head=str(rec.get("enlarger_head") or "standard"),
                    paper_dev=str(rec.get("paper_dev") or "neutral"),
                    paper_base=str(rec.get("paper_base") or "none"),
                    bw_grade00=float(rec.get("bw_grade00", 0.0) or 0.0),
                    bw_grade5=float(rec.get("bw_grade5", 0.0) or 0.0),
                    bw_preflash=float(rec.get("bw_preflash", 0.0) or 0.0),
                    toner_shadows=str(rec.get("toner_shadows") or "none"),
                    toner_shadows_amt=float(rec.get("toner_shadows_amt", 0.0) or 0.0),
                    toner_highlights=str(rec.get("toner_highlights") or "none"),
                    toner_highlights_amt=float(rec.get("toner_highlights_amt", 0.0) or 0.0),
                    farmer_bleach=float(rec.get("farmer_bleach", 0.0) or 0.0),
                    rotate=int(rec.get("rotate", 0) or 0),
                    flip_h=bool(rec.get("flip_h", False)),
                    flip_v=bool(rec.get("flip_v", False)),
                    straighten=float(rec.get("straighten", 0.0) or 0.0),
                    crop_rect=rec.get("crop_rect"),
                    max_dim=None,
                    return_float=True,
                )
            save_output_image(
                img,
                out_file,
                source_path=src,
                quality=max(60, min(100, int(args.quality or 96))),
                float_srgb=srgb_f,
                analog_meta=analog_meta,
                easel_border=easel_border,
                dry_down_comp=dry_down,
                export_max_dim=args.max_dim,
            )
            developed_images.append(img)
            print(f"  [{idx}/{len(frames)}] {fname} -> {out_file.name} ({time.time() - t0:.2f}s)")

        if args.sheet and developed_images:
            sheet_path = out_dir / "SHEET_PROJECT.jpg"
            sheet = generate_contact_sheet(
                developed_images,
                roll_name=str(proj_data.get("name") or "HALURO").upper(),
                film_name=f"Proyecto · {len(developed_images)} fotos",
            )
            sheet.save(sheet_path, quality=93, subsampling=0)
            print(f"\n  Hoja de contactos creada: {sheet_path}")

    print(f"\n  Proyecto renderizado en {time.time() - t_start:.2f}s · Carpeta: {out_dir}\n")


if __name__ == "__main__":
    main()
