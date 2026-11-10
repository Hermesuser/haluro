#!/usr/bin/env python3
"""Haluro — Social Media Promo Video Generator (Vertical 9:16 - 1080x1920)
With authentic Chilean Spanish Voice-over Narration & Analog Darkroom Soundtrack.

Duration: 35.0 seconds (1050 frames @ 30 fps)
Voice: es-CL-LorenzoNeural (Chilean Spanish)
Output: dist/Haluro_Promo_Reel_1080x1920.mp4
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
OUTPUT_MP4 = DIST_DIR / "Haluro_Promo_Reel_1080x1920.mp4"

WIDTH, HEIGHT = 1080, 1920
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


VIEW_W, VIEW_H = 920, 613


def load_view_image(name: str) -> Image.Image:
    p = SAMPLES_DIR / name
    im = Image.open(p).convert("RGB")
    scale = max(VIEW_W / im.width, VIEW_H / im.height)
    new_w, new_h = int(im.width * scale), int(im.height * scale)
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - VIEW_W) // 2
    top = (new_h - VIEW_H) // 2
    return im.crop((left, top, left + VIEW_W, top + VIEW_H))


print("==> [1/3] Preparando fotogramas de muestra...")
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
    ICON_IMG = ICON_IMG.resize((140, 140), Image.Resampling.LANCZOS)


def generate_audio_track() -> Path:
    """Generate Chilean Spanish voiceover and mix with warm ambient darkroom audio."""
    print("==> [2/3] Generando locución en español chileno (es-CL-LorenzoNeural)...")
    segments = [
        ("s1.mp3", "¿Cansado de pagar suscripciones para revelar tus negativos analógicos?", "+8%"),
        ("s2.mp3", "Te presento Haluro: inversión sensitométrica que elimina la máscara naranja con color de laboratorio tradicional.", "+10%"),
        ("s3.mp3", "Setenta y dos emulsiones clásicas: Portra, CineStill, Velvia y diez virados químicos de cuarto oscuro.", "+8%"),
        ("s4.mp3", "Análisis unificado de todo el rollo sin saltos de exposición y TIFF real de 16 bits.", "+8%"),
        ("s5.mp3", "Cien por ciento local y privado. Tus fotos nunca van a la nube.", "+8%"),
        ("s6.mp3", "Descárgalo gratis en GitHub. Haluro: laboratorio analógico digital, hecho en Chile.", "+6%"),
    ]

    async def _synth():
        for fname, text, rate in segments:
            c = edge_tts.Communicate(text, "es-CL-LorenzoNeural", rate=rate)
            await c.save(f"/tmp/{fname}")

    asyncio.run(_synth())

    # Build timed voiceover
    voice_track = Path("/tmp/voiceover_full.mp3")
    cmd_voice = [
        "/opt/homebrew/bin/ffmpeg", "-y",
        "-i", "/tmp/s1.mp3",
        "-i", "/tmp/s2.mp3",
        "-i", "/tmp/s3.mp3",
        "-i", "/tmp/s4.mp3",
        "-i", "/tmp/s5.mp3",
        "-i", "/tmp/s6.mp3",
        "-filter_complex",
        "[0]adelay=300|300[a0];"
        "[1]adelay=4800|4800[a1];"
        "[2]adelay=11200|11200[a2];"
        "[3]adelay=17500|17500[a3];"
        "[4]adelay=23000|23000[a4];"
        "[5]adelay=27800|27800[a5];"
        "[a0][a1][a2][a3][a4][a5]amix=inputs=6:dropout_transition=0:normalize=0[voice];"
        "[voice]volume=1.35[out]",
        "-map", "[out]",
        "-t", "35.0",
        str(voice_track),
    ]
    subprocess.run(cmd_voice, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Master with subtle analog warm ambient bed
    soundtrack = Path("/tmp/soundtrack_final.m4a")
    cmd_mix = [
        "/opt/homebrew/bin/ffmpeg", "-y",
        "-f", "lavfi", "-i", "anoisesrc=c=pink:r=44100:a=0.003,lowpass=f=2500",
        "-f", "lavfi", "-i", "sine=frequency=130.81:r=44100,volume=0.035",
        "-f", "lavfi", "-i", "sine=frequency=196.00:r=44100,volume=0.025",
        "-f", "lavfi", "-i", "sine=frequency=311.13:r=44100,volume=0.018",
        "-i", str(voice_track),
        "-filter_complex",
        "[0][1][2][3]amix=inputs=4:dropout_transition=0[bed];"
        "[bed]afade=t=in:ss=0:d=1.5,afade=t=out:st=33.5:d=1.5[music];"
        "[4]volume=1.35[voice];"
        "[music][voice]amix=inputs=2:dropout_transition=0:normalize=0[mix]",
        "-map", "[mix]",
        "-c:a", "aac", "-b:a", "192k",
        "-t", "35.0",
        str(soundtrack),
    ]
    subprocess.run(cmd_mix, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return soundtrack


def draw_sprocket_borders(draw: ImageDraw.ImageDraw, frame_x: int, frame_y: int, w: int, h: int) -> None:
    border_h = 44
    draw.rectangle([frame_x, frame_y - border_h, frame_x + w, frame_y], fill=(6, 7, 9))
    draw.rectangle([frame_x, frame_y + h, frame_x + w, frame_y + h + border_h], fill=(6, 7, 9))

    sprock_w, sprock_h = 24, 16
    sprock_rad = 4
    spacing = 54
    for x in range(frame_x + 16, frame_x + w - 16, spacing):
        draw.rounded_rectangle([x, frame_y - 30, x + sprock_w, frame_y - 30 + sprock_h], radius=sprock_rad, fill=(2, 2, 3))
        draw.rounded_rectangle([x, frame_y + h + 14, x + sprock_w, frame_y + h + 14 + sprock_h], radius=sprock_rad, fill=(2, 2, 3))

    f_tiny = get_font(18, bold=True)
    draw.text((frame_x + 30, frame_y - 40), "KODAK SAFETY FILM 400", fill=(180, 130, 40), font=f_tiny)
    draw.text((frame_x + w - 120, frame_y - 40), "24A ▶", fill=(180, 130, 40), font=f_tiny)
    draw.text((frame_x + 30, frame_y + h + 30), "HALURO LAB · C-41", fill=(180, 130, 40), font=f_tiny)
    draw.text((frame_x + w - 120, frame_y + h + 30), "ISO 400", fill=(180, 130, 40), font=f_tiny)


def render_frame(frame_num: int) -> Image.Image:
    base = Image.new("RGB", (WIDTH, HEIGHT), BG_DARK)
    draw = ImageDraw.Draw(base)

    # Ambient top glow
    for r in range(160, 0, -20):
        alpha_val = int(14 * (r / 160))
        draw.ellipse([WIDTH // 2 - r * 2, -100, WIDTH // 2 + r * 2, r * 2], fill=(alpha_val + 13, 15, 18))

    # Header
    bx = (WIDTH - 380) // 2
    draw.rounded_rectangle([bx, 110, bx + 380, 156], radius=23, fill=(35, 25, 15), outline=COLOR_AMBER, width=2)
    draw.text((bx + 24, 122), "🇨🇱 HALURO v2.4.0 · SOFTWARE LIBRE", fill=COLOR_AMBER, font=get_font(20, bold=True))

    draw.text((WIDTH // 2, 205), "Laboratorio Analógico Digital", fill=COLOR_WHITE, font=get_font(52, bold=True), anchor="mt")
    draw.text((WIDTH // 2, 275), "Revelado Sensitométrico & Emulaciones Químicas", fill=COLOR_GRAY, font=get_font(26, bold=False), anchor="mt")

    # Film Viewport
    frame_x = (WIDTH - VIEW_W) // 2
    frame_y = 380
    draw_sprocket_borders(draw, frame_x, frame_y, VIEW_W, VIEW_H)

    # 35-second Timeline:
    # 0 - 135   (0.0s - 4.5s) : Scene 1 - Raw C-41 Negative
    # 135 - 330 (4.5s - 11.0s): Scene 2 - Wipe Slider H&D Inversion
    # 330 - 525 (11.0s - 17.5s): Scene 3 - 72 Emulsions Showcase
    # 525 - 690 (17.5s - 23.0s): Scene 4 - Roll Analysis & Contact Sheet
    # 690 - 840 (23.0s - 28.0s): Scene 5 - Privacy & Core Values
    # 840 - 1050 (28.0s - 35.0s): Scene 6 - Outro & GitHub CTA

    if frame_num < 135:
        base.paste(IMG_NEGATIVE, (frame_x, frame_y))
        tag_text = "NEGATIVO COLOR C-41 (MÁSCARA NARANJA D-MIN)"
        tag_color = (190, 80, 20)
        h1 = "¿Cansado de pagar suscripciones"
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
        draw.ellipse([divider_x - 22, frame_y + VIEW_H // 2 - 22, divider_x + 22, frame_y + VIEW_H // 2 + 22], fill=COLOR_AMBER, outline=COLOR_WHITE, width=3)
        draw.text((divider_x, frame_y + VIEW_H // 2), "◀ ▶", fill=(10, 10, 10), font=get_font(18, bold=True), anchor="mm")

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
            h1 = "Tonos de Piel Cálidos y Suaves"
            h2 = "El estándar del retrato editorial analógico"
        elif sub_f < 100:
            base.paste(IMG_CINESTILL, (frame_x, frame_y))
            tag_text = "EMULACIÓN 2/72 · CINESTILL 800T"
            h1 = "Halación Roja en Altas Luces"
            h2 = "Emulsión de cine Tungsteno con grano volumétrico"
        elif sub_f < 150:
            base.paste(IMG_VELVIA, (frame_x, frame_y))
            tag_text = "EMULACIÓN 3/72 · FUJIFILM VELVIA 50"
            h1 = "Diapositiva E-6 Saturada"
            h2 = "Verdes vivos y contraste mítico de paisaje"
        else:
            base.paste(IMG_TMAX, (frame_x, frame_y))
            tag_text = "EMULACIÓN 4/72 · KODAK T-MAX 400"
            h1 = "Virado Químico al Selenio"
            h2 = "10 procesos químicos de cuarto oscuro Fine-Art"
        tag_color = COLOR_AMBER
        sub_text = "72 emulsiones clásicas calibradas con matrices 3D LUT"

    elif frame_num < 690:
        base.paste(IMG_CONTACT, (frame_x, frame_y))
        tag_text = "ANÁLISIS UNIFICADO DE ROLLO & HOJAS DE CONTACTO"
        tag_color = (60, 120, 200)
        h1 = "Cero Saltos de Exposición"
        h2 = "Hoja de Contactos con 1 Clic"
        sub_text = "Exportación maestra en TIFF real de 16 bits (48-bit RGB)"

    elif frame_num < 840:
        base.paste(IMG_INVERTED, (frame_x, frame_y))
        tag_text = "100% LIBRE · 100% LOCAL Y PRIVADO"
        tag_color = (130, 70, 200)
        h1 = "Tus Fotos Nunca Van a la Nube"
        h2 = "Sin Cuentas, Sin Suscripciones"
        sub_text = "Edición 100% no destructiva nativa para macOS y Windows 11"

    else:
        base.paste(IMG_PORTRA, (frame_x, frame_y))
        tag_text = "DISPONIBLE AHORA PARA MACOS & WINDOWS 11"
        tag_color = COLOR_AMBER
        h1 = "Descarga Libre en GitHub"
        h2 = "github.com/Hermesuser/haluro"
        sub_text = "Por César Fernández Ardiles (Oregano · Chile)"

    # Tag on film viewport
    f_tag = get_font(20, bold=True)
    t_box = draw.textbbox((0, 0), tag_text, font=f_tag)
    tw = t_box[2] - t_box[0] + 32
    tx = (WIDTH - tw) // 2
    ty = frame_y + VIEW_H - 56
    draw.rounded_rectangle([tx, ty, tx + tw, ty + 40], radius=8, fill=(10, 12, 16), outline=tag_color, width=2)
    draw.text((tx + 16, ty + 10), tag_text, fill=tag_color, font=f_tag)

    # Lower Information Area
    card_x = 70
    card_w = WIDTH - 140
    card_y = 1040
    card_h = 760

    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=24, fill=BG_CARD, outline=BORDER_CARD, width=2)

    draw.text((WIDTH // 2, card_y + 60), h1, fill=COLOR_WHITE, font=get_font(44, bold=True), anchor="mt")
    draw.text((WIDTH // 2, card_y + 120), h2, fill=COLOR_AMBER_LIGHT, font=get_font(40, bold=True), anchor="mt")
    draw.text((WIDTH // 2, card_y + 185), sub_text, fill=COLOR_GRAY, font=get_font(26, bold=False), anchor="mt")

    features = [
        ("✨ Inversión Sensitométrica H&D", "Resta matemática de máscara naranja C-41 y B&W"),
        ("🎨 72 Emulsiones Clásicas", "Portra, Tri-X, Velvia, CineStill 800T, HP5+, Gold"),
        ("🧪 10 Virados Químicos Reales", "Selenio (3 grados), Platino/Paladio, Sulfuro Sepia"),
        ("💾 TIFF Real de 16 Bits", "RGB de 48 bits, metadatos EXIF y hojas de contactos"),
        ("🍏 macOS & 🪟 Windows 11", "Aplicación de escritorio nativa sin dependencias"),
    ]

    fy = card_y + 250
    for title, desc in features:
        draw.text((card_x + 40, fy), title, fill=COLOR_WHITE, font=get_font(26, bold=True))
        draw.text((card_x + 40, fy + 32), desc, fill=COLOR_MUTED, font=get_font(20, bold=False))
        fy += 68

    btn_y = card_y + card_h - 120
    draw.rounded_rectangle([card_x + 40, btn_y, card_x + card_w - 40, btn_y + 80], radius=16, fill=COLOR_AMBER)
    draw.text((WIDTH // 2, btn_y + 40), "DESCARGA GRATIS EN GITHUB  ▶", fill=(10, 10, 12), font=get_font(30, bold=True), anchor="mm")

    if ICON_IMG:
        base.paste(ICON_IMG, (WIDTH // 2 - 70, card_y - 70), ICON_IMG)

    return base


def main() -> None:
    soundtrack = generate_audio_track()

    print(f"==> [3/3] Renderizando video promocional Reel (1080x1920 @ 30fps) con audio chileno...")
    ffmpeg_cmd = [
        "/opt/homebrew/bin/ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "-",  # Video pipe
        "-i", str(soundtrack),  # Chilean Audio Track
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
        frame = render_frame(i)
        proc.stdin.write(frame.tobytes())
        if (i + 1) % 60 == 0:
            sec = (i + 1) // FPS
            sys.stdout.write(f"\r    Renderizado: {i+1}/{TOTAL_FRAMES} fotogramas ({sec}s / 35s)...")
            sys.stdout.flush()

    proc.stdin.close()
    proc.wait()

    print(f"\n==> ¡Video promocional vertical con locución chilena generado en:\n    {OUTPUT_MP4}")


if __name__ == "__main__":
    main()
