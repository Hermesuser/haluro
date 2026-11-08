"""Generates authentic vintage film contact sheets (SHEET.jpg) for developed rolls.
Includes roll header, film canister branding, frame markers, and negative sprockets.
"""

from pathlib import Path
from PIL import Image, ImageDraw
import math

from .platform_io import load_ui_font


def generate_contact_sheet(
    frame_images,
    roll_name="ROLL 001",
    film_name="Kodak Portra 400",
    date_str=None,
    columns=4,
    thumb_width=480
):
    """frame_images: list of PIL Images or file paths.
    Returns: PIL Image of the contact sheet.
    """
    if not date_str:
        import datetime
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    if not frame_images:
        return Image.new("RGB", (800, 600), (14, 14, 16))
        
    loaded_frames = []
    for item in frame_images:
        if isinstance(item, (str, Path)):
            loaded_frames.append(Image.open(item).convert("RGB"))
        else:
            loaded_frames.append(item.convert("RGB"))
            
    n_frames = len(loaded_frames)
    rows = math.ceil(n_frames / columns)
    
    # Calculate dimensions
    margin_x = 40
    margin_top = 130
    margin_bottom = 60
    spacing_x = 24
    spacing_y = 48
    
    # Target frame aspect ratio approx 3:2
    thumb_h = int(thumb_width * 2 / 3)
    
    total_w = margin_x * 2 + columns * thumb_width + (columns - 1) * spacing_x
    total_h = margin_top + margin_bottom + rows * thumb_h + (rows - 1) * spacing_y
    
    # Darkroom photographic paper background (near black)
    sheet = Image.new("RGB", (total_w, total_h), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)
    
    # Header Fonts (cross-platform: macOS, Windows 11, Linux)
    title_font = load_ui_font("sans-bold", 32)
    meta_font = load_ui_font("mono", 18)
    frame_font = load_ui_font("mono-bold", 14)
        
    # Draw Header & Amber Film Rule
    draw.rectangle([margin_x, 30, total_w - margin_x, 34], fill=(220, 140, 30))
    draw.text((margin_x, 48), film_name.upper(), font=title_font, fill=(240, 240, 240))
    draw.text((margin_x, 88), f"ROLL: {roll_name}   •   FRAMES: {n_frames}   •   DATE: {date_str}", font=meta_font, fill=(180, 180, 180))
    
    # Draw Film Canister Badge
    badge_w, badge_h = 160, 40
    bx = total_w - margin_x - badge_w
    by = 50
    draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h], radius=6, fill=(28, 30, 35), outline=(229, 149, 40), width=2)
    draw.text((bx + 24, by + 12), "HALURO LAB", font=frame_font, fill=(229, 149, 40))
    
    # Draw Frames
    for idx, frame in enumerate(loaded_frames):
        r = idx // columns
        c = idx % columns
        
        x = margin_x + c * (thumb_width + spacing_x)
        y = margin_top + r * (thumb_h + spacing_y)
        
        # Fit image maintaining aspect ratio
        thumb = frame.copy()
        thumb.thumbnail((thumb_width, thumb_h), Image.Resampling.LANCZOS)
        
        # Center inside slot
        px = x + (thumb_width - thumb.width) // 2
        py = y + (thumb_h - thumb.height) // 2
        
        # Film rebate border
        border_pad = 4
        draw.rectangle(
            [px - border_pad, py - border_pad, px + thumb.width + border_pad, py + thumb.height + border_pad],
            outline=(45, 45, 50),
            width=1
        )
        
        sheet.paste(thumb, (px, py))
        
        # Frame Number Marker (e.g. "01", "02")
        frame_str = f"▶ {idx + 1:02d}A  DX"
        draw.text((px, py + thumb.height + 6), frame_str, font=frame_font, fill=(190, 120, 20))
        
    return sheet
