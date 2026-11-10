#!/usr/bin/env python3
"""Haluro — Social Media Promo Video Generator (Horizontal 16:9 - 1920x1080)
With authentic Chilean Spanish Voice-over Narration & Analog Darkroom Soundtrack.

Duration: 35.0 seconds (1050 frames @ 30 fps)
Voice: es-CL-LorenzoNeural (Chilean Spanish)
Output: dist/Haluro_Promo_Landscape_1920x1080.mp4
"""

from pathlib import Path
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = REPO_ROOT / "assets"
SAMPLES_DIR = REPO_ROOT / "samples"
DIST_DIR = REPO_ROOT / "dist"
DIST_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_MP4 = DIST_DIR / "Haluro_Promo_Landscape_1920x1080.mp4"

WIDTH, HEIGHT = 1920, 1080
FPS = 30
TOTAL_FRAMES = 1050  # 35.0 seconds

# Colors
BG_DARK = (13, 15, 18)
BG_CARD = (22, 26, 32)
BORDER_CARD = (42, 48, 60)
COLOR_AMBER = (229, 149, 40)
COLOR_AMBER_LIGHT = (255, 185, 90)
COLOR_WHITE = (248, 250, 252)
COLOR_GRAY = (160, 172, 188)
COLOR_MUTED = (100, 110, 125)

FONT_BOLD_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"


def get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


VIEW_W, VIEW_H = 1000, 667


def load_view_image(name: str) -> Image.Image:
    p = SAMPLES_DIR / name
    im = Image.open(p).convert("RGB")
    scale = max(VIEW_W / im.width, VIEW_H / im.height)
    new_w, new_h = int(im.width * scale), int(im.height * scale)
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - VIEW_W) // 2
    top = (new_h - VIEW_H) // 2
    return im.crop((left, top, left + VIEW_W, top + VIEW_H))


print("==> [1/2] Preparando fotogramas landscape...")
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
    ICON_IMG = ICON_IMG.resize((96, 96), Image.Resampling.LANCZOS)


def draw_sprocket_borders(draw: ImageDraw.ImageDraw, frame_x: int, frame_y: int, w: int, h: int) -> None:
    border_h = 40
    draw.rectangle([frame_x, frame_y - border_h, frame_x + w, frame_y], fill=(6, 7, 9))
    draw.rectangle([frame_x, frame_y + h, frame_x + w, frame_y + h + border_h], fill=(6, 7, 9))

    sprock_w, sprock_h = 24, 16
    sprock_rad = 4
    spacing = 55
    for x in range(frame_x + 16, frame_x + w - 16, spacing):
        draw.rounded_rectangle([x, frame_y - 28, x + sprock_w, frame_y - 28 + sprock_h], radius=sprock_rad, fill=(2, 2, 3))
        draw.rounded_rectangle([x, frame_y + h + 12, x + sprock_w, frame_y + h + 12 + sprock_h], radius=sprock_rad, fill=(2, 2, 3))

    f_tiny = get_font(16, bold=True)
    draw.text((frame_x + 25, frame_y - 36), "KODAK SAFETY FILM · C-41", fill=(180, 130, 40), font=f_tiny)
    draw.text((frame_x + w - 100, frame_y - 36), "24A ▶", fill=(180, 130, 40), font=f_tiny)
    draw.text((frame_x + 25, frame_y + h + 24), "HALURO LAB · SENSITOMETRY", fill=(180, 130, 40), font=f_tiny)


def render_landscape_frame(frame_num: int) -> Image.Image:
    base = Image.new("RGB", (WIDTH, HEIGHT), BG_DARK)
    draw = ImageDraw.Draw(base)

    draw.ellipse([WIDTH // 4 - 200, -150, WIDTH // 4 + 200, 250], fill=(22, 18, 16))

    # Left: Film Viewport (X: 70, Y: 210)
    frame_x = 70
    frame_y = 210
    draw_sprocket_borders(draw, frame_x, frame_y, VIEW_W, VIEW_H)

    # Right: Information Card (X: 1110, Y: 120, W: 740, H: 840)
    card_x = 1110
    card_y = 120
    card_w = 740
    card_h = 840
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=24, fill=BG_CARD, outline=BORDER_CARD, width=2)

    # Header top bar on left
    draw.rounded_rectangle([frame_x, 80, frame_x + 460, 130], radius=25, fill=(35, 25, 15), outline=COLOR_AMBER, width=2)
    draw.text((frame_x + 24, 93), "🇨🇱 HALURO v2.4.0 · SOFTWARE LIBRE", fill=COLOR_AMBER, font=get_font(20, bold=True))
    draw.text((frame_x + 480, 93), "Nativo para macOS & Windows 11", fill=COLOR_GRAY, font=get_font(22, bold=False))

    # 35-second Timeline:
    # 0 - 135   (0.0s - 4.5s) : Scene 1 - Raw C-41 Negative
    # 135 - 330 (4.5s - 11.0s): Scene 2 - Wipe Slider H&D Inversion
    # 330 - 525 (11.0s - 17.5s): Scene 3 - 72 Emulsions Showcase
    # 525 - 690 (17.5s - 23.0s): Scene 4 - Roll Analysis & Contact Sheet
    # 690 - 840 (23.0s - 28.0s): Scene 5 - Privacy & Core Values
    # 840 - 1050 (28.0s - 35.0s): Scene 6 - Outro & GitHub CTA

    if frame_num < 135:
        base.paste(IMG_NEGATIVE, (frame_x, frame_y))
        tag_text = "NEGATIVO COLOR C-41 (MÁSCARA NARANJA)"
        tag_color = (190, 80, 20)
        h1 = "¿Cansado de suscripciones"
        h2 = "para revelar tus negativos?"
        sub_text = "Digitaliza con tu cámara o escáner sin atarte a Lightroom"
    elif frame_num < 330:
        progress = (frame_num - 135) / 195.0
        wipe_x = int(VIEW_W * (0.04 + 0.92 * (3 * progress**2 - 2 * progress**3)))
        comp = IMG_NEGATIVE.copy()
        crop_pos = IMG_INVERTED.crop((0, 0, wipe_x, VIEW_H))
        comp.paste(crop_pos, (0, 0))
        base.paste(comp, (frame_x, frame_y))

        divider_x = frame_x + wipe_x
        draw.line([(divider_x, frame_y), (divider_x, frame_y + VIEW_H)], fill=COLOR_AMBER, width=4)
        draw.ellipse([divider_x - 20, frame_y + VIEW_H // 2 - 20, divider_x + 20, frame_y + VIEW_H // 2 + 20], fill=COLOR_AMBER, outline=COLOR_WHITE, width=2)

        tag_text = "INVERSIÓN SENSITOMÉTRICA HURTER–DRIFFIELD"
        tag_color = (40, 140, 70)
        h1 = "Eliminación Matemática D-min"
        h2 = "Color Puro de Papel Fuji RA-4"
        sub_text = "Resta la máscara naranja preservando altas luces y sombras reales"
    elif frame_num < 525:
        sub_f = frame_num - 330
        if sub_f < 50:
            base.paste(IMG_PORTRA, (frame_x, frame_y))
            tag_text = "EMULACIÓN 1/72 · KODAK PORTRA 400"
            h1 = "Tonos de Piel Cálidos"
            h2 = "El estándar del retrato editorial"
        elif sub_f < 100:
            base.paste(IMG_CINESTILL, (frame_x, frame_y))
            tag_text = "EMULACIÓN 2/72 · CINESTILL 800T"
            h1 = "Halación Roja en Luces"
            h2 = "Capa antihalo y estética de cine"
        elif sub_f < 150:
            base.paste(IMG_VELVIA, (frame_x, frame_y))
            tag_text = "EMULACIÓN 3/72 · FUJIFILM VELVIA 50"
            h1 = "Diapositiva E-6 Saturada"
            h2 = "Verdes vivos y contraste mítico"
        else:
            base.paste(IMG_TMAX, (frame_x, frame_y))
            tag_text = "EMULACIÓN 4/72 · KODAK T-MAX 400"
            h1 = "Virado al Selenio Fine-Art"
            h2 = "10 procesos químicos de cuarto oscuro"
        tag_color = COLOR_AMBER
        sub_text = "72 emulsiones clásicas calibradas con matrices 3D LUT"
    elif frame_num < 690:
        base.paste(IMG_CONTACT, (frame_x, frame_y))
        tag_text = "ANÁLISIS UNIFICADO DE ROLLO & CONTACTOS"
        tag_color = (60, 120, 200)
        h1 = "Cero Saltos de Exposición"
        h2 = "Hojas de Contacto en 1 Clic"
        sub_text = "Exportación maestra en TIFF real de 16 bits (48-bit RGB)"
    elif frame_num < 840:
        base.paste(IMG_INVERTED, (frame_x, frame_y))
        tag_text = "100% LIBRE · 100% LOCAL Y PRIVADO"
        tag_color = (130, 70, 200)
        h1 = "Tus Fotos No Van a la Nube"
        h2 = "Sin Cuentas, Sin Pagos Mensuales"
        sub_text = "Edición 100% no destructiva nativa para macOS y Windows 11"
    else:
        base.paste(IMG_PORTRA, (frame_x, frame_y))
        tag_text = "DISPONIBLE AHORA PARA MACOS & WINDOWS 11"
        tag_color = COLOR_AMBER
        h1 = "Descarga Libre en GitHub"
        h2 = "github.com/Hermesuser/haluro"
        sub_text = "Por César Fernández Ardiles (Oregano · Chile)"

    f_tag = get_font(18, bold=True)
    t_box = draw.textbbox((0, 0), tag_text, font=f_tag)
    tw = t_box[2] - t_box[0] + 30
    draw.rounded_rectangle([frame_x + 20, frame_y + VIEW_H - 50, frame_x + 20 + tw, frame_y + VIEW_H - 12], radius=8, fill=(10, 12, 16), outline=tag_color, width=2)
    draw.text((frame_x + 35, frame_y + VIEW_H - 43), tag_text, fill=tag_color, font=f_tag)

    if ICON_IMG:
        base.paste(ICON_IMG, (card_x + 50, card_y + 45), ICON_IMG)

    draw.text((card_x + 165, card_y + 55), "HALURO", fill=COLOR_AMBER, font=get_font(38, bold=True))
    draw.text((card_x + 165, card_y + 102), "Laboratorio Analógico Digital", fill=COLOR_WHITE, font=get_font(24, bold=False))

    draw.text((card_x + 50, card_y + 180), h1, fill=COLOR_WHITE, font=get_font(38, bold=True))
    draw.text((card_x + 50, card_y + 235), h2, fill=COLOR_AMBER_LIGHT, font=get_font(34, bold=True))
    draw.text((card_x + 50, card_y + 295), sub_text, fill=COLOR_GRAY, font=get_font(22, bold=False))

    features = [
        ("✨ Inversión Sensitométrica H&D", "Resta matemática de máscara naranja C-41 y B&W"),
        ("🎨 72 Emulsiones Clásicas", "Portra, Tri-X, Velvia, CineStill 800T, HP5+, Gold"),
        ("🧪 10 Virados Químicos Reales", "Selenio (3 grados), Platino/Paladio, Sulfuro Sepia"),
        ("💾 TIFF Real de 16 Bits", "RGB de 48 bits, metadatos EXIF y hojas de contactos"),
        ("🍏 macOS & 🪟 Windows 11", "Aplicación de escritorio nativa sin dependencias"),
    ]
    fy = card_y + 360
    for title, desc in features:
        draw.text((card_x + 50, fy), title, fill=COLOR_WHITE, font=get_font(24, bold=True))
        draw.text((card_x + 50, fy + 30), desc, fill=COLOR_MUTED, font=get_font(19, bold=False))
        fy += 68

    btn_y = card_y + card_h - 100
    draw.rounded_rectangle([card_x + 50, btn_y, card_x + card_w - 50, btn_y + 68], radius=14, fill=COLOR_AMBER)
    draw.text((card_x + card_w // 2, btn_y + 34), "DESCARGA GRATIS EN GITHUB  ▶", fill=(10, 10, 12), font=get_font(26, bold=True), anchor="mm")

    return base


def main() -> None:
    soundtrack = Path("/tmp/soundtrack_final.m4a")

    print(f"==> [2/2] Renderizando video promocional Landscape (1920x1080 @ 30fps) con audio chileno...")
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
        "-t", "35.0",
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
        frame = render_landscape_frame(i)
        proc.stdin.write(frame.tobytes())
        if (i + 1) % 60 == 0:
            sec = (i + 1) // FPS
            sys.stdout.write(f"\r    Renderizado: {i+1}/{TOTAL_FRAMES} fotogramas ({sec}s / 35s)...")
            sys.stdout.flush()

    proc.stdin.close()
    proc.wait()

    print(f"\n==> ¡Video landscape con audio chileno generado en:\n    {OUTPUT_MP4}")


if __name__ == "__main__":
    main()
