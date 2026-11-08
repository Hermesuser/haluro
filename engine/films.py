"""Catalog of all 72 film stocks supported by Haluro.
Includes color parameters, grain, halation, contrast, LUT mappings and UI metadata.
"""

from pathlib import Path
import re

from .platform_io import get_resource_root

# Base directory for bundled 3D LUT files (supports both source & frozen .app/.exe)
LUT_DIR = get_resource_root() / "luts"

# Descriptions for all 72 films
DESCRIPTIONS = {
    # Built-in films
    "portra400": "Soft warm skin, gentle highlights",
    "gold200": "Golden hour, all day long",
    "ektar100": "Punchy colour, ultra fine grain",
    "superia400": "Green shadows, everyday snaps",
    "velvia50": "Vivid slide film, hard contrast",
    "cinestill800t": "Tungsten cine film, night goes blue",
    "hp5": "Classic British B&W, honest midtones",
    "trix400": "Gritty contrast, street classic",
    "cinestill400t": "Tungsten cine film, daylight balanced",
    # Film-Luts
    "portra160": "Fine grain, natural skin tones",
    "portra800": "Low light portraits, warm grain",
    "portra160nc": "Natural colour, soft contrast",
    "portra160vc": "Vivid colour for portraits",
    "portra400nc": "Neutral skin, quiet colour",
    "portra400vc": "More colour, same skin tones",
    "portra400uc": "Ultra colour, punchy everyday",
    "elite200": "Bright consumer colour",
    "elite400": "Everyday colour, more speed",
    "pro160c": "Crisp colour, cool and clean",
    "pro400h": "Airy pastels, fourth colour layer",
    "pro800z": "Night portraits, soft palette",
    "reala100": "True-to-life colour, fine grain",
    "superia100": "Clean daylight colour",
    "superia200": "Fuji greens, everyday snaps",
    "superia800": "Indoor speed, Fuji colour",
    "superia1600": "Night snaps, bold grain",
    "xtra800": "Fast all-rounder, cool shadows",
    "vista200": "Warm reds, holiday colour",
    "ultra100": "Saturated, punchy Agfa colour",
    "redscale100": "Shot through the back: red-orange",
    "velvia100": "Rich colour, softer than the 50",
    "provia100f": "Neutral slide, faithful colour",
    "provia400f": "Fast slide, clean colour",
    "provia400x": "Fast slide, finer grain",
    "astia100f": "Soft slide film for skin",
    "sensia100": "Bright consumer slide",
    "kodachrome25": "Legendary fine grain, deep reds",
    "kodachrome64": "Magazine colour of the 70s",
    "kodachrome200": "Faster Kodachrome, warm grain",
    "e100gx": "Warm, gentle Ektachrome",
    "e100vs": "Very saturated Ektachrome",
    "elitechrome200": "Everyday Kodak slide",
    "elitechrome400": "Fast Kodak slide, more grain",
    "extracolor100": "Extra saturated Kodak slide",
    "precisa100": "Cool, crisp Agfa slide",
    "elite100xpro": "Slide in C-41: wild contrast",
    "superia200xpro": "Cross-processed, yellow highlights",
    "xproslide200": "Cross-process blues and yellows",
    "tmax100": "Ultra fine grain, smooth tones",
    "tmax400": "Sharp, modern B&W",
    "tmax3200": "Push-ready, grainy nights",
    "bw400cn": "Chromogenic B&W, smooth grain",
    "hie": "Infrared: white leaves, dark skies",
    "delta100": "Fine, sharp modern B&W",
    "delta400": "Smooth grain at 400",
    "delta3200": "Pushes into the dark",
    "fp4": "Classic medium speed B&W",
    "panf50": "Slow, super fine grain",
    "hps800": "Fast classic Ilford",
    "xp2": "C-41 B&W, smooth tones",
    "acros100": "Fine grain, deep blacks",
    "neopan1600": "Fast and contrasty B&W",
    "apx25": "Very fine, slow Agfa B&W",
    "apx100": "Classic Agfa B&W",
    "retro80s": "Extended red, dark skies",
    "retro100": "Soft tonal B&W",
    "ortho25": "Orthochromatic: reds go dark",
    "ir400": "Infrared touch, glowing foliage",
    "kodak2383": "Cinema print: teal shadows",
    "kodak2393": "Cinema print, richer blacks",
    "fuji3510": "Fuji print film, soft colour",
    "fuji3513": "Fuji print for digital masters",
}

CATEGORY_NAMES = {
    "neg": "Colour Negative (C-41)",
    "slide": "Colour Slide (E-6)",
    "cine": "Cinema Stocks",
    "bw": "Black & White",
    "xpro": "Cross-Processed",
    "print": "Motion Picture Print",
}

STOCKS_DATA = [
    # colour negative
    ("portra160", "negative_new/kodak_portra_160", "Kodak", "Portra 160", 160, "neg"),
    ("portra800", "negative_new/kodak_portra_800", "Kodak", "Portra 800", 800, "neg"),
    ("portra160nc", "negative_old/kodak_portra_160_nc", "Kodak", "Portra 160NC", 160, "neg"),
    ("portra160vc", "negative_old/kodak_portra_160_vc", "Kodak", "Portra 160VC", 160, "neg"),
    ("portra400nc", "negative_old/kodak_portra_400_nc", "Kodak", "Portra 400NC", 400, "neg"),
    ("portra400vc", "negative_old/kodak_portra_400_vc", "Kodak", "Portra 400VC", 400, "neg"),
    ("portra400uc", "negative_old/kodak_portra_400_uc", "Kodak", "Portra 400UC", 400, "neg"),
    ("elite200", "negative_color/kodak_elite_color_200", "Kodak", "Elite Color 200", 200, "neg"),
    ("elite400", "negative_color/kodak_elite_color_400", "Kodak", "Elite Color 400", 400, "neg"),
    ("pro160c", "negative_new/fuji_160c", "Fujifilm", "Pro 160C", 160, "neg"),
    ("pro400h", "negative_new/fuji_400h", "Fujifilm", "Pro 400H", 400, "neg"),
    ("pro800z", "negative_new/fuji_800z", "Fujifilm", "Pro 800Z", 800, "neg"),
    ("reala100", "negative_color/fuji_superia_reala_100", "Fujifilm", "Reala 100", 100, "neg"),
    ("superia100", "negative_old/fuji_superia_100", "Fujifilm", "Superia 100", 100, "neg"),
    ("superia200", "negative_color/fuji_superia_200", "Fujifilm", "Superia 200", 200, "neg"),
    ("superia800", "negative_old/fuji_superia_800", "Fujifilm", "Superia 800", 800, "neg"),
    ("superia1600", "negative_old/fuji_superia_1600", "Fujifilm", "Superia 1600", 1600, "neg"),
    ("xtra800", "negative_color/fuji_superia_x-tra_800", "Fujifilm", "X-TRA 800", 800, "neg"),
    ("vista200", "negative_color/agfa_vista_200", "Agfa", "Vista 200", 200, "neg"),
    ("ultra100", "negative_color/agfa_ultra_color_100", "Agfa", "Ultra 100", 100, "neg"),
    ("redscale100", "negative_color/lomography_redscale_100", "Lomography", "Redscale 100", 100, "neg"),
    # colour reversal
    ("velvia100", "colorslide/fuji_velvia_100_generic", "Fujifilm", "Velvia 100", 100, "slide"),
    ("provia100f", "colorslide/fuji_provia_100f", "Fujifilm", "Provia 100F", 100, "slide"),
    ("provia400f", "colorslide/fuji_provia_400f", "Fujifilm", "Provia 400F", 400, "slide"),
    ("provia400x", "colorslide/fuji_provia_400x", "Fujifilm", "Provia 400X", 400, "slide"),
    ("astia100f", "colorslide/fuji_astia_100f", "Fujifilm", "Astia 100F", 100, "slide"),
    ("sensia100", "colorslide/fuji_sensia_100", "Fujifilm", "Sensia 100", 100, "slide"),
    ("kodachrome25", "colorslide/kodak_kodachrome_25", "Kodak", "Kodachrome 25", 25, "slide"),
    ("kodachrome64", "colorslide/kodak_kodachrome_64", "Kodak", "Kodachrome 64", 64, "slide"),
    ("kodachrome200", "colorslide/kodak_kodachrome_200", "Kodak", "Kodachrome 200", 200, "slide"),
    ("e100gx", "colorslide/kodak_e-100_gx_ektachrome_100", "Kodak", "Ektachrome E100GX", 100, "slide"),
    ("e100vs", "colorslide/kodak_ektachrome_100_vs", "Kodak", "Ektachrome E100VS", 100, "slide"),
    ("elitechrome200", "colorslide/kodak_elite_chrome_200", "Kodak", "Elite Chrome 200", 200, "slide"),
    ("elitechrome400", "colorslide/kodak_elite_chrome_400", "Kodak", "Elite Chrome 400", 400, "slide"),
    ("extracolor100", "colorslide/kodak_elite_extracolor_100", "Kodak", "ExtraColor 100", 100, "slide"),
    ("precisa100", "colorslide/agfa_precisa_100", "Agfa", "Precisa 100", 100, "slide"),
    # cross-processed
    ("elite100xpro", "negative_color/kodak_elite_100_xpro", "Kodak", "Elite 100 X-Pro", 100, "xpro"),
    ("superia200xpro", "colorslide/fuji_superia_200_xpro", "Fujifilm", "Superia 200 X-Pro", 200, "xpro"),
    ("xproslide200", "colorslide/lomography_x-pro_slide_200", "Lomography", "X-Pro Slide 200", 200, "xpro"),
    # black and white
    ("tmax100", "bw/kodak_t-max_100", "Kodak", "T-MAX 100", 100, "bw"),
    ("tmax400", "bw/kodak_t-max_400", "Kodak", "T-MAX 400", 400, "bw"),
    ("tmax3200", "bw/kodak_t-max_3200", "Kodak", "T-MAX P3200", 3200, "bw"),
    ("bw400cn", "bw/kodak_bw_400_cn", "Kodak", "BW400CN", 400, "bw"),
    ("hie", "bw/kodak_hie_hs_infra", "Kodak", "HIE Infrared", 400, "bw"),
    ("delta100", "bw/ilford_delta_100", "Ilford", "Delta 100", 100, "bw"),
    ("delta400", "bw/ilford_delta_400", "Ilford", "Delta 400", 400, "bw"),
    ("delta3200", "bw/ilford_delta_3200", "Ilford", "Delta 3200", 3200, "bw"),
    ("fp4", "bw/ilford_fp_4_plus_125", "Ilford", "FP4 Plus", 125, "bw"),
    ("panf50", "bw/ilford_pan_f_plus_50", "Ilford", "Pan F Plus", 50, "bw"),
    ("hps800", "bw/ilford_hps_800", "Ilford", "HPS 800", 800, "bw"),
    ("xp2", "bw/ilford_xp_2", "Ilford", "XP2 Super", 400, "bw"),
    ("acros100", "bw/fuji_neopan_acros_100", "Fujifilm", "Acros 100", 100, "bw"),
    ("neopan1600", "bw/fuji_neopan_1600", "Fujifilm", "Neopan 1600", 1600, "bw"),
    ("apx25", "bw/agfa_apx_25", "Agfa", "APX 25", 25, "bw"),
    ("apx100", "bw/agfa_apx_100", "Agfa", "APX 100", 100, "bw"),
    ("retro80s", "bw/rollei_retro_80s", "Rollei", "Retro 80S", 80, "bw"),
    ("retro100", "bw/rollei_retro_100_tonal", "Rollei", "Retro 100 Tonal", 100, "bw"),
    ("ortho25", "bw/rollei_ortho_25", "Rollei", "Ortho 25", 25, "bw"),
    ("ir400", "bw/rollei_ir_400", "Rollei", "Infrared 400", 400, "bw"),
    # cinema print stocks
    ("kodak2383", "print/kodak_2383_constlmap", "Kodak", "Vision 2383", 200, "print"),
    ("kodak2393", "print/kodak_2393_constlmap", "Kodak", "Vision 2393", 200, "print"),
    ("fuji3510", "print/fuji_3510_constlmap", "Fujifilm", "Eterna 3510", 200, "print"),
    ("fuji3513", "print/fuji_3513_constlmap", "Fujifilm", "Eterna 3513", 200, "print"),
]


def grain_for(iso, kind):
    steps = {25: 0, 50: 1, 64: 1.3, 80: 1.6, 100: 2, 125: 2.3, 160: 2.7, 200: 3,
             400: 4, 800: 5, 1600: 6, 3200: 7}.get(iso, 3)
    amount = 0.006 + 0.0045 * steps
    if kind == "slide":
        amount *= 0.7
    if kind == "print":
        amount = 0.008
    return round(amount, 4), round(0.7 + 0.11 * steps, 2)


def make_film(key, rel_lut_path, brand, name, iso, kind):
    amount, size = grain_for(iso, kind)
    f = dict(
        key=key,
        brand=brand,
        name=f"{brand} {name}",
        iso=iso,
        kind=kind,
        balance=5500,
        lut_file=f"{rel_lut_path}.cube",
        lut_space="srgb",
        ev=0.2 if kind == "neg" else 0.0,
        sat=1.0,
        contrast=(0.18, 0.18, 0.18),
        pivot=(0.0, 0.0, 0.0),
        black=(0.03, 0.03, 0.03),
        white=(0.96, 0.96, 0.96),
        halation=0.8,
        hal_thr=0.75,
        hal_tint=(1.0, 0.28, 0.06),
        grain=amount,
        grain_size=size,
        soft=0.7,
        desc=DESCRIPTIONS.get(key, "")
    )
    if kind in ("slide", "xpro"):
        f.update(slide=True, contrast=(0.22, 0.22, 0.22), black=(0.015,) * 3, white=(0.98,) * 3,
                 halation=0.4, soft=0.5)
    if kind == "bw":
        f.update(mono=(0.30, 0.59, 0.11), contrast=(0.19,), pivot=(0.0,), black=(0.03,), white=(0.96,),
                 halation=0.4)
    if kind == "print":
        f.update(halation=0.5, soft=0.5)
    return f


FILMS = {
    # 8 Custom Mathematical Film Recipes
    "portra400": dict(
        key="portra400", brand="Kodak", name="Kodak Portra 400", iso=400, kind="neg", balance=5500, ev=0.3, sat=0.85,
        contrast=(0.165, 0.17, 0.158), pivot=(-0.15, 0.0, 0.1),
        black=(0.03, 0.026, 0.028), white=(0.97, 0.955, 0.92),
        hues=[("orange", "red", 0.06, 1.05), ("green", "yellow", 0.12, 0.85),
              ("blue", "cyan", 0.08, 0.85)],
        halation=1.0, hal_thr=0.75, hal_tint=(1.0, 0.28, 0.06), grain=0.018, grain_size=1.1, soft=0.7,
        desc=DESCRIPTIONS.get("portra400", "")
    ),
    "cinestill800t": dict(
        key="cinestill800t", brand="CineStill", name="CineStill 800T", iso=800, kind="cine", balance=3200, ev=0.0, sat=0.95,
        contrast=(0.18, 0.18, 0.172), pivot=(-0.05, 0.0, -0.05),
        black=(0.02, 0.032, 0.045), white=(0.97, 0.96, 0.95),
        hues=[("cyan", "blue", 0.1, 1.0), ("red", "orange", 0.08, 1.05)],
        halation=6.0, hal_thr=0.6, hal_tint=(1.0, 0.20, 0.05), grain=0.026, grain_size=1.4, soft=0.8,
        desc=DESCRIPTIONS.get("cinestill800t", "")
    ),
    "ektar100": dict(
        key="ektar100", brand="Kodak", name="Kodak Ektar 100", iso=100, kind="neg", balance=5500, ev=0.0, sat=1.25,
        contrast=(0.19, 0.19, 0.186), pivot=(-0.05, 0.0, 0.05),
        black=(0.025, 0.02, 0.025), white=(0.98, 0.97, 0.95),
        hues=[("red", "magenta", 0.05, 1.1), ("blue", "blue", 0.0, 1.15)],
        halation=0.6, hal_thr=0.75, hal_tint=(1.0, 0.28, 0.06), grain=0.009, grain_size=0.8, soft=0.5,
        desc=DESCRIPTIONS.get("ektar100", "")
    ),
    "gold200": dict(
        key="gold200", brand="Kodak", name="Kodak Gold 200", iso=200, kind="neg", balance=5500, ev=0.2, sat=1.08,
        contrast=(0.185, 0.18, 0.168), pivot=(-0.25, -0.05, 0.2),
        black=(0.035, 0.028, 0.022), white=(0.98, 0.95, 0.86),
        hues=[("yellow", "orange", 0.1, 1.1), ("green", "yellow", 0.15, 0.9)],
        halation=1.0, hal_thr=0.75, hal_tint=(1.0, 0.32, 0.08), grain=0.016, grain_size=1.1, soft=0.7,
        desc=DESCRIPTIONS.get("gold200", "")
    ),
    "superia400": dict(
        key="superia400", brand="Fujifilm", name="Fujicolor Superia 400", iso=400, kind="neg", balance=5500, ev=0.1, sat=1.05,
        contrast=(0.18, 0.183, 0.178), pivot=(0.05, -0.1, 0.0),
        black=(0.022, 0.036, 0.032), white=(0.96, 0.97, 0.95),
        hues=[("green", "cyan", 0.18, 1.05), ("red", "magenta", 0.06, 1.0),
              ("yellow", "green", 0.06, 0.95)],
        halation=1.0, hal_thr=0.75, hal_tint=(1.0, 0.25, 0.08), grain=0.02, grain_size=1.2, soft=0.7,
        desc=DESCRIPTIONS.get("superia400", "")
    ),
    "velvia50": dict(
        key="velvia50", brand="Fujifilm", name="Fujichrome Velvia 50", iso=50, kind="slide", balance=5500, slide=True, ev=-0.3, sat=1.45,
        contrast=(0.25, 0.25, 0.25), pivot=(0.0, 0.0, -0.05),
        black=(0.01, 0.01, 0.015), white=(0.98, 0.98, 0.98),
        hues=[("green", "green", 0.0, 1.15), ("blue", "magenta", 0.06, 1.15),
              ("red", "magenta", 0.06, 1.1)],
        halation=0.3, hal_thr=0.8, hal_tint=(1.0, 0.28, 0.06), grain=0.007, grain_size=0.7, soft=0.5,
        desc=DESCRIPTIONS.get("velvia50", "")
    ),
    "hp5": dict(
        key="hp5", brand="Ilford", name="Ilford HP5 Plus 400", iso=400, kind="bw", balance=5500, ev=0.2,
        mono=(0.30, 0.60, 0.10),
        contrast=(0.175,), pivot=(0.0,), black=(0.03,), white=(0.96,),
        halation=0.4, hal_thr=0.75, hal_tint=(1.0, 1.0, 1.0), grain=0.028, grain_size=1.3, soft=0.7,
        desc=DESCRIPTIONS.get("hp5", "")
    ),
    "trix400": dict(
        key="trix400", brand="Kodak", name="Kodak Tri-X 400", iso=400, kind="bw", balance=5500, ev=0.0,
        mono=(0.42, 0.48, 0.10),
        contrast=(0.205,), pivot=(0.1,), black=(0.02,), white=(0.97,),
        halation=0.4, hal_thr=0.75, hal_tint=(1.0, 1.0, 1.0), grain=0.036, grain_size=1.3, soft=0.6,
        desc=DESCRIPTIONS.get("trix400", "")
    ),
    "cinestill400t": dict(
        key="cinestill400t", brand="CineStill", name="CineStill 400T", iso=400, kind="cine", balance=5500, ev=0.0, sat=0.95,
        contrast=(0.175, 0.175, 0.168), pivot=(-0.05, 0.0, -0.05),
        black=(0.02, 0.03, 0.04), white=(0.97, 0.96, 0.95),
        hues=[("cyan", "blue", 0.1, 1.0), ("red", "orange", 0.08, 1.05)],
        halation=3.0, hal_thr=0.65, hal_tint=(1.0, 0.22, 0.05), grain=0.022, grain_size=1.3, soft=0.75,
        desc=DESCRIPTIONS.get("cinestill400t", "")
    ),
}

# Append the remaining 63 stocks
for entry in STOCKS_DATA:
    key = entry[0]
    FILMS[key] = make_film(*entry)


def get_film(key):
    return FILMS.get(key, FILMS["portra400"])


def list_films():
    return [
        {
            "key": f["key"],
            "name": f["name"],
            "brand": f["brand"],
            "iso": f["iso"],
            "kind": f["kind"],
            "category": CATEGORY_NAMES.get(f["kind"], "Film"),
            "desc": f["desc"]
        }
        for f in FILMS.values()
    ]
