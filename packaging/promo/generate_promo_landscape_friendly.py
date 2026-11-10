#!/usr/bin/env python3
"""Haluro — Video Promocional Cercano y Amigable para Fotógrafos (Horizontal 16:9 - 1920x1080)
Con narración empática en español chileno (es-CL-LorenzoNeural) y música de cuarto oscuro.

Duración: 42.0 segundos (1260 fotogramas @ 30 fps)
Salida: dist/Haluro_Promo_Landscape_Amigable_1920x1080.mp4
"""

import asyncio
from pathlib import Path
import subprocess
import sys
import edge_tts
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = REPO_ROOT / "assets"
SAMPLES_DIR = REPO_ROOT / "samples"
DIST_DIR = REPO_ROOT / "dist"
DIST_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_MP4 = DIST_DIR / "Haluro_Promo_Landscape_Amigable_1920x1080.mp4"

WIDTH, HEIGHT = 1920, 1080
FPS = 30
TOTAL_FRAMES = 1260  # 42.0 segundos

BG_DARK = (14, 15, 18)
BG_CARD = (23, 26, 32)
BORDER_CARD = (45, 52, 65)
COLOR_AMBER = (235, 155, 45)
COLOR_AMBER_LIGHT = (255, 195, 105)
COLOR_WHITE = (248, 250, 252)
COLOR_GRAY = (165, 175, 190)
COLOR_MUTED = (110, 120, 135)

FONT_BOLD_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"


def get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


VIEW_W, VIEW_H = 1040, 693


def load_view_image(name: str) -> Image.Image:
    p = SAMPLES_DIR / name
    im = Image.open(p).convert("RGB")
    scale = max(VIEW_W / im.width, VIEW_H / im.height)
    new_w, new_h = int(im.width * scale), int(im.height * scale)
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - VIEW_W) // 2
    top = (new_h - VIEW_H) // 2
    return im.crop((left, top, left + VIEW_W, top + VIEW_H))


print("==> [1/3] Cargando imágenes y emulsiones fotográficas (Landscape)...")
IMG_NEGATIVE = load_view_image("SAMPLE_NEGATIVE.jpg")
IMG_INVERTED = load_view_image("test_inverted_positive.jpg")
IMG_PORTRA = load_view_image("test_portra400.jpg")
IMG_CINESTILL = load_view_image("test_cinestill800t.jpg")
IMG_VELVIA = load_view_image("test_velvia50.jpg")
IMG_TMAX = load_view_image("test_tmax400.jpg")
IMG_CONTACT = load_view_image("contact_sheet.jpg")

ICON_IMG = None
if (ASSETS_DIR / "haluro_256.png").is_file():
    ICON_IMG = Image.open(ASSETS_DIR / "haluro_256.png").convert("RGBA")
    ICON_IMG = ICON_IMG.resize((120, 120), Image.Resampling.LANCZOS)


def generate_audio_track() -> Path:
    soundtrack = Path("/tmp/soundtrack_cercano.m4a")
    if soundtrack.is_file():
        return soundtrack

    voice_track = Path("/tmp/voice_cercano.mp3")
    cmd_mix = [
        "/opt/homebrew/bin/ffmpeg", "-y",
        "-f", "lavfi", "-i", "anoisesrc=c=pink:r=44100:a=0.002,lowpass=f=2000",
        "-f", "lavfi", "-i", "sine=frequency=130.81:r=44100,volume=0.030",
        "-f", "lavfi", "-i", "sine=frequency=196.00:r=44100,volume=0.022",
        "-f", "lavfi", "-i", "sine=frequency=261.63:r=44100,volume=0.018",
        "-i", str(voice_track),
        "-filter_complex",
        "[0][1][2][3]amix=inputs=4:dropout_transition=0[bed];"
        "[bed]afade=t=in:ss=0:d=1.8,afade=t=out:st=40.2:d=1.8[music];"
        "[4]volume=1.35[voice];"
        "[music][voice]amix=inputs=2:dropout_transition=0:normalize=0[mix]",
        "-map", "[mix]",
        "-c:a", "aac", "-b:a", "192k",
        "-t", "42.0",
        str(soundtrack),
    ]
    subprocess.run(cmd_mix, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return soundtrack


def draw_sprocket_borders(draw: ImageDraw.ImageDraw, frame_x: int, frame_y: int, w: int, h: int) -> None:
    border_h = 36
    draw.rectangle([frame_x, frame_y - border_h, frame_x + w, frame_y], fill=(7, 8, 10))
    draw.rectangle([frame_x, frame_y + h, frame_x + w, frame_y + h + border_h], fill=(7, 8, 10))

    sprock_w, sprock_h = 24, 14
    sprock_rad = 3
    spacing = 54
    for x in range(frame_x + 16, frame_x + w - 16, spacing):
        draw.rounded_rectangle([x, frame_y - 25, x + sprock_w, frame_y - 25 + sprock_h], radius=sprock_rad, fill=(2, 2, 3))
        draw.rounded_rectangle([x, frame_y + h + 11, x + sprock_w, frame_y + h + 11 + sprock_h], radius=sprock_rad, fill=(2, 2, 3))

    f_tiny = get_font(16, bold=True)
    draw.text((frame_x + 25, frame_y - 32), "KODAK SAFETY FILM 400", fill=(195, 140, 45), font=f_tiny)
    draw.text((frame_x + w - 100, frame_y - 32), "24A ▶", fill=(195, 140, 45), font=f_tiny)
    draw.text((frame_x + 25, frame_y + h + 24), "HALURO · CUARTO OSCURO", fill=(195, 140, 45), font=f_tiny)
    draw.text((frame_x + w - 100, frame_y + h + 24), "ISO 400", fill=(195, 140, 45), font=f_tiny)


def render_frame(frame_num: int) -> Image.Image:
    base = Image.new("RGB", (WIDTH, HEIGHT), BG_DARK)
    draw = ImageDraw.Draw(base)

    # Ambient Top Glow
    for r in range(200, 0, -25):
        alpha_val = int(12 * (r / 200))
        draw.ellipse([400 - r * 2, -100, 400 + r * 2, r * 2], fill=(alpha_val + 14, 15, 18))

    # Header Bar
    draw.rounded_rectangle([60, 50, 480, 96], radius=23, fill=(35, 25, 15), outline=COLOR_AMBER, width=2)
    draw.text((80, 62), "📷 DE FOTÓGRAFO A FOTÓGRAFO", fill=COLOR_AMBER, font=get_font(20, bold=True))

    draw.text((510, 73), "Haluro · Laboratorio Analógico Digital", fill=COLOR_WHITE, font=get_font(28, bold=True), anchor="lm")
    draw.text((WIDTH - 60, 73), "100% LIBRE · CERO NUBE · PRIVADO", fill=COLOR_GRAY, font=get_font(20, bold=False), anchor="rm")

    # Left Film Viewport
    frame_x = 60
    frame_y = 170
    draw_sprocket_borders(draw, frame_x, frame_y, VIEW_W, VIEW_H)

    # 42 seconds (1260 frames)
    if frame_num < 225:
        base.paste(IMG_NEGATIVE, (frame_x, frame_y))
        tag_text = "NEGATIVO COLOR C-41 (MÁSCARA NARANJA D-MIN)"
        tag_color = (200, 90, 30)
        h1 = "¿Escaneas negativos en casa?"
        h2 = "Pelear con curvas RGB no debería ser normal"
        sub_text = "Diseñado para ahorrarte horas de ajuste y mensualidades caras"
        badge_text = "💬 DE FOTÓGRAFO A FOTÓGRAFO"

    elif frame_num < 435:
        progress = (frame_num - 225) / 210.0
        wipe_x = int(VIEW_W * (0.04 + 0.92 * (3 * progress**2 - 2 * progress**3)))
        comp = IMG_NEGATIVE.copy()
        crop_pos = IMG_INVERTED.crop((0, 0, wipe_x, VIEW_H))
        comp.paste(crop_pos, (0, 0))
        base.paste(comp, (frame_x, frame_y))

        divider_x = frame_x + wipe_x
        draw.line([(divider_x, frame_y), (divider_x, frame_y + VIEW_H)], fill=COLOR_AMBER, width=4)
        draw.ellipse([divider_x - 20, frame_y + VIEW_H // 2 - 20, divider_x + 20, frame_y + VIEW_H // 2 + 20], fill=COLOR_AMBER, outline=COLOR_WHITE, width=3)
        draw.text((divider_x, frame_y + VIEW_H // 2), "◀ ▶", fill=(10, 10, 10), font=get_font(16, bold=True), anchor="mm")

        tag_text = "INVERSIÓN SENSITOMÉTRICA HURTER–DRIFFIELD"
        tag_color = (45, 150, 75)
        h1 = "Color Real de Papel Químico"
        h2 = "Sin suscripciones ni presets tramposos"
        sub_text = "Resta matemática de máscara naranja preservando altas luces reales"
        badge_text = "✨ REVELADO NATURAL RA-4"

    elif frame_num < 645:
        sub_f = frame_num - 435
        if sub_f < 55:
            base.paste(IMG_PORTRA, (frame_x, frame_y))
            tag_text = "KODAK PORTRA 400 · TONOS CÁLIDOS"
            h1 = "Tonos de Piel Suaves y Orgánicos"
            h2 = "El estándar de oro para retrato analógico"
        elif sub_f < 105:
            base.paste(IMG_CINESTILL, (frame_x, frame_y))
            tag_text = "CINESTILL 800T · HALACIÓN NOCTURNA"
            h1 = "Halación de Cine en Altas Luces"
            h2 = "El resplandor bermellón de la película 35mm"
        elif sub_f < 155:
            base.paste(IMG_VELVIA, (frame_x, frame_y))
            tag_text = "FUJIFILM VELVIA 50 · DIAPOSITIVA E-6"
            h1 = "Verdes Vivos y Contraste Mítico"
            h2 = "La mística de la diapositiva en tus paisajes"
        else:
            base.paste(IMG_TMAX, (frame_x, frame_y))
            tag_text = "ILFORD & KODAK B&W · VIRADOS QUÍMICOS"
            h1 = "Textura Viva del Grano de Plata"
            h2 = "Selenio, Sepia y Platino/Paladio tradicional"
        tag_color = COLOR_AMBER
        sub_text = "72 emulsiones de Kodak, Fuji, Ilford, Agfa y Cine"
        badge_text = "🎞️ 72 PELÍCULAS CLÁSICAS"

    elif frame_num < 825:
        base.paste(IMG_CONTACT, (frame_x, frame_y))
        tag_text = "ANÁLISIS UNIFICADO DE ROLLO COMPLETO"
        tag_color = (65, 130, 215)
        h1 = "Revela Todo tu Rollo de una Vez"
        h2 = "Cero saltos de exposición entre fotos"
        sub_text = "Hojas de contacto automáticas y exportación TIFF de 16 bits"
        badge_text = "📋 HOJAS DE CONTACTO & TIFF 16-BIT"

    elif frame_num < 1005:
        base.paste(IMG_INVERTED, (frame_x, frame_y))
        tag_text = "100% LOCAL · TUS FOTOS SON TUYAS"
        tag_color = (140, 80, 210)
        h1 = "Sin Cuentas, Sin Nube, Sin Costo"
        h2 = "Tus fotos se quedan en tu computador"
        sub_text = "Software 100% privado y libre para macOS y Windows 11"
        badge_text = "🔒 PRIVACIDAD & CÓDIGO ABIERTO"

    else:
        base.paste(IMG_PORTRA, (frame_x, frame_y))
        tag_text = "PROYECTO LIBRE · HECHO EN CHILE 🇨🇱"
        tag_color = COLOR_AMBER
        h1 = "Te Invito a Probarlo en GitHub"
        h2 = "github.com/Hermesuser/haluro"
        sub_text = "Por César Fernández Ardiles · ¡Buenas fotos!"
        badge_text = "🤝 UN ABRAZO Y BUENAS FOTOS"

    # Etiqueta sobre el visor izquierdo
    f_tag = get_font(18, bold=True)
    t_box = draw.textbbox((0, 0), tag_text, font=f_tag)
    tw = t_box[2] - t_box[0] + 32
    tx = frame_x + (VIEW_W - tw) // 2
    ty = frame_y + VIEW_H - 52
    draw.rounded_rectangle([tx, ty, tx + tw, ty + 36], radius=8, fill=(10, 12, 16), outline=tag_color, width=2)
    draw.text((tx + 16, ty + 8), tag_text, fill=tag_color, font=f_tag)

    # Right Card
    card_x = 1140
    card_w = 720
    card_y = 170
    card_h = VIEW_H

    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=24, fill=BG_CARD, outline=BORDER_CARD, width=2)

    # Chip destacado superior
    chip_f = get_font(18, bold=True)
    cb = draw.textbbox((0, 0), badge_text, font=chip_f)
    cw = cb[2] - cb[0] + 28
    draw.rounded_rectangle([card_x + 40, card_y + 40, card_x + 40 + cw, card_y + 72], radius=16, fill=(35, 30, 20), outline=COLOR_AMBER, width=1)
    draw.text((card_x + 54, card_y + 47), badge_text, fill=COLOR_AMBER, font=chip_f)

    draw.text((card_x + 40, card_y + 95), h1, fill=COLOR_WHITE, font=get_font(36, bold=True))
    draw.text((card_x + 40, card_y + 145), h2, fill=COLOR_AMBER_LIGHT, font=get_font(32, bold=True))
    draw.text((card_x + 40, card_y + 200), sub_text, fill=COLOR_GRAY, font=get_font(21, bold=False))

    features = [
        ("✨ Revelado Sensitométrico H&D", "Inversión fotoquímica pura que resta la máscara naranja"),
        ("🎨 72 Emulsiones Clásicas", "Portra, CineStill, Tri-X, Velvia, Gold, HP5+, Ektar"),
        ("🔬 Halación & Grano Real", "Estructura física orgánica según el ISO de cada película"),
        ("🎞️ Rollo Completo & TIFF 16-bit", "Consistencia total de color y máxima calidad de archivo"),
        ("🍏 macOS & 🪟 Windows 11", "100% nativo, privado y sin cuentas ni suscripciones"),
    ]

    fy = card_y + 260
    for title, desc in features:
        draw.text((card_x + 40, fy), title, fill=COLOR_WHITE, font=get_font(23, bold=True))
        draw.text((card_x + 40, fy + 28), desc, fill=COLOR_MUTED, font=get_font(18, bold=False))
        fy += 64

    btn_y = card_y + card_h - 100
    draw.rounded_rectangle([card_x + 40, btn_y, card_x + card_w - 40, btn_y + 68], radius=14, fill=COLOR_AMBER)
    draw.text((card_x + card_w // 2, btn_y + 34), "DESCARGA GRATIS EN GITHUB  ▶", fill=(10, 10, 12), font=get_font(25, bold=True), anchor="mm")

    if ICON_IMG:
        base.paste(ICON_IMG, (card_x + card_w - 140, card_y + 25), ICON_IMG)

    return base


def main() -> None:
    soundtrack = generate_audio_track()

    print("==> [3/3] Renderizando video promocional Landscape (1920x1080 @ 30fps)...")
    ffmpeg_cmd = [
        "/opt/homebrew/bin/ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "-",
        "-i", str(soundtrack),
        "-t", "42.0",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "19",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(OUTPUT_MP4),
    ]

    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    for i in range(TOTAL_FRAMES):
        frame = render_frame(i)
        proc.stdin.write(frame.tobytes())
        if (i + 1) % 90 == 0:
            sec = (i + 1) // FPS
            sys.stdout.write(f"\r    Renderizado: {i+1}/{TOTAL_FRAMES} fotogramas ({sec}s / 42s)...")
            sys.stdout.flush()

    proc.stdin.close()
    proc.wait()

    print(f"\n==> ¡Video promocional Landscape cercano y amigable generado en:\n    {OUTPUT_MP4}")


if __name__ == "__main__":
    main()
