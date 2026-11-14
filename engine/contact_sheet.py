"""Generates authentic vintage film contact sheets (SHEET.jpg) for developed rolls.
Includes roll header, film canister branding, frame markers, and negative sprockets.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

from .platform_io import load_ui_font


def generate_contact_sheet(
    frame_images,
    roll_name="ROLLO 001",
    film_name="Kodak Portra 400",
    date_str=None,
    columns=4,
    thumb_width=480,
    return_layout=False,
    frame_labels=None,
):
    """frame_images: list of PIL Images or file paths.
    columns: integer number of columns (typically 3, 4, 5, or 6).
    return_layout: bool, if True returns tuple (sheet_image, layout_boxes).
    frame_labels: optional list of per-frame identifiers (stems) shown next to DX numbers.
    Returns: PIL Image of the contact sheet (or tuple if return_layout=True).
    """
    if not date_str:
        import datetime
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    try:
        columns = max(2, min(8, int(columns)))
    except (ValueError, TypeError):
        columns = 4

    if not frame_images:
        empty = Image.new("RGB", (800, 600), (14, 14, 16))
        return (empty, []) if return_layout else empty

    loaded_frames = []
    for item in frame_images:
        if isinstance(item, (str, Path)):
            with Image.open(item) as src:
                frame = src.convert("RGB")
        else:
            frame = item.convert("RGB")

        # Reduce to the thumbnail size *immediately*. Keeping every frame at
        # full resolution made a 36-frame 24 MP roll consume ~7 GB of RAM and
        # frequently killed the process with an out-of-memory kill.
        if frame.width > thumb_width * 2 or frame.height > thumb_width * 2:
            frame.thumbnail((thumb_width * 2, thumb_width * 2), Image.Resampling.LANCZOS)
        loaded_frames.append(frame)

    n_frames = len(loaded_frames)
    rows = math.ceil(n_frames / columns)

    # Scale layout and typography proportionally with thumbnail resolution
    scale = max(0.5, float(thumb_width) / 480.0)
    margin_x = int(round(40 * scale))
    margin_top = int(round(130 * scale))
    margin_bottom = int(round(60 * scale))
    spacing_x = int(round(24 * scale))
    spacing_y = int(round(48 * scale))

    # Adaptive slot height: compact 3:2 when all frames are landscape,
    # taller balanced 0.88:1 when vertical/square frames exist
    has_portrait_or_square = any(im.height > im.width * 0.90 for im in loaded_frames)
    thumb_h = int(round(thumb_width * (0.88 if has_portrait_or_square else 2 / 3)))

    total_w = margin_x * 2 + columns * thumb_width + (columns - 1) * spacing_x
    total_h = margin_top + margin_bottom + rows * thumb_h + (rows - 1) * spacing_y

    # Darkroom photographic paper background (near black)
    sheet = Image.new("RGB", (total_w, total_h), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)

    # Header Fonts (cross-platform: macOS, Windows 11, Linux)
    title_font = load_ui_font("sans-bold", int(round(32 * scale)))
    meta_font = load_ui_font("mono", int(round(18 * scale)))
    frame_font = load_ui_font("mono-bold", int(round(14 * scale)))

    # Draw Header & Amber Film Rule
    rule_h = max(2, int(round(4 * scale)))
    rule_y = int(round(30 * scale))
    draw.rectangle([margin_x, rule_y, total_w - margin_x, rule_y + rule_h], fill=(220, 140, 30))
    draw.text((margin_x, int(round(48 * scale))), film_name.upper(), font=title_font, fill=(240, 240, 240))
    draw.text(
        (margin_x, int(round(88 * scale))),
        f"ROLLO: {roll_name}   •   CUADROS: {n_frames}   •   FECHA: {date_str}",
        font=meta_font,
        fill=(180, 180, 180),
    )

    # Draw Film Canister Badge with accurately centered text
    badge_w, badge_h = int(round(160 * scale)), int(round(40 * scale))
    bx = total_w - margin_x - badge_w
    by = int(round(50 * scale))
    draw.rounded_rectangle(
        [bx, by, bx + badge_w, by + badge_h],
        radius=max(3, int(round(6 * scale))),
        fill=(28, 30, 35),
        outline=(229, 149, 40),
        width=max(1, int(round(2 * scale))),
    )
    badge_text = "HALURO LAB"
    bbox = draw.textbbox((0, 0), badge_text, font=frame_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = bx + (badge_w - tw) / 2 - bbox[0]
    ty = by + (badge_h - th) / 2 - bbox[1]
    draw.text((tx, ty), badge_text, font=frame_font, fill=(229, 149, 40))

    # Draw Frames
    border_pad = max(2, int(round(4 * scale)))
    layout_boxes = []
    for idx, frame in enumerate(loaded_frames):
        r = idx // columns
        c = idx % columns

        x = margin_x + c * (thumb_width + spacing_x)
        y = margin_top + r * (thumb_h + spacing_y)

        # Fit image maintaining aspect ratio inside slot
        too_wide = frame.width > thumb_width
        too_tall = frame.height > thumb_h
        too_small = frame.width < thumb_width and frame.height < thumb_h
        if too_wide or too_tall or too_small:
            thumb = frame.copy()
            thumb.thumbnail((thumb_width, thumb_h), Image.Resampling.BICUBIC)
        else:
            thumb = frame

        # Center inside slot
        px = x + (thumb_width - thumb.width) // 2
        py = y + (thumb_h - thumb.height) // 2

        # Film rebate border
        draw.rectangle(
            [px - border_pad, py - border_pad, px + thumb.width + border_pad, py + thumb.height + border_pad],
            outline=(45, 45, 50),
            width=max(1, int(round(1 * scale)))
        )

        sheet.paste(thumb, (px, py))

        # Frame Number Marker + optional custom filename stem
        lbl_suffix = ""
        if frame_labels and idx < len(frame_labels) and frame_labels[idx]:
            raw_lbl = str(frame_labels[idx]).strip()
            if len(raw_lbl) > 14:
                raw_lbl = raw_lbl[:13] + "…"
            lbl_suffix = f" · {raw_lbl}"
        frame_str = f"▶ {idx + 1:02d}A  DX{lbl_suffix}"
        draw.text((px, py + thumb.height + int(round(6 * scale))), frame_str, font=frame_font, fill=(190, 120, 20))

        layout_boxes.append({
            "index": idx,
            "x_pct": round(px / total_w, 5),
            "y_pct": round(py / total_h, 5),
            "w_pct": round(thumb.width / total_w, 5),
            "h_pct": round(thumb.height / total_h, 5),
        })

    return (sheet, layout_boxes) if return_layout else sheet
