"""Catalog of all 72 film stocks supported by Haluro.
Includes color parameters, grain, halation, contrast, LUT mappings and UI metadata.
"""

from pathlib import Path
import re

from .platform_io import get_resource_root

# Base directory for bundled 3D LUT files (supports both source & frozen .app/.exe)
LUT_DIR = get_resource_root() / "luts"

# Descriptions for all 72 films (natural Spanish)
DESCRIPTIONS = {
    # Built-in films
    "portra400": "Piel cálida y suave, luces altas delicadas",
    "gold200": "Hora dorada durante todo el día",
    "ektar100": "Color intenso y grano ultrafino",
    "superia400": "Sombras verdosas, uso diario versátil",
    "velvia50": "Diapositiva vívida de alto contraste",
    "cinestill800t": "Cine tungsteno, noches en azul profundo",
    "hp5": "B&N británico clásico, tonos medios fieles",
    "trix400": "Contraste marcado, clásico callejero",
    "cinestill400d": "Cine luz día (5500K), halación cálida en luces",
    # Film-Luts
    "portra160": "Grano fino y tonos de piel naturales",
    "portra800": "Retratos en poca luz, grano cálido",
    "portra160nc": "Color natural y contraste suave",
    "portra160vc": "Color vívido ideal para retrato",
    "portra400nc": "Piel neutra y color contenido",
    "portra400vc": "Más saturación manteniendo la piel natural",
    "portra400uc": "Ultra colorido, vibrante para diario",
    "elite200": "Color luminoso de película familiar",
    "elite400": "Color cotidiano con mayor sensibilidad",
    "pro160c": "Color nítido, limpio y algo frío",
    "pro400h": "Tonos pastel luminosos de cuatro capas",
    "pro800z": "Retratos nocturnos con paleta suave",
    "reala100": "Color fiel a la realidad y grano fino",
    "superia100": "Color limpio optimizado para luz día",
    "superia200": "Verdes Fuji característicos para diario",
    "superia800": "Sensibilidad de interior con sello Fuji",
    "superia1600": "Escenas nocturnas con grano con carácter",
    "xtra800": "Todoterreno rápida de sombras frías",
    "vista200": "Rojos cálidos con aire de viaje",
    "ultra100": "Color Agfa saturado y vibrante",
    "redscale100": "Expuesta al revés: rojo anaranjado intenso",
    "velvia100": "Color rico, más suave que Velvia 50",
    "provia100f": "Diapositiva neutra de color muy fiel",
    "provia400f": "Diapositiva rápida de color limpio",
    "provia400x": "Diapositiva rápida con grano más fino",
    "astia100f": "Diapositiva suave para tono de piel",
    "sensia100": "Diapositiva brillante de uso general",
    "kodachrome25": "Grano fino legendario y rojos profundos",
    "kodachrome64": "Color editorial clásico de los años 70",
    "kodachrome200": "Kodachrome más rápida de grano cálido",
    "e100gx": "Ektachrome cálido y equilibrado",
    "e100vs": "Ektachrome de saturación muy alta",
    "elitechrome200": "Diapositiva Kodak versátil de diario",
    "elitechrome400": "Diapositiva Kodak rápida con más grano",
    "extracolor100": "Diapositiva Kodak con saturación extra",
    "precisa100": "Diapositiva Agfa fresca y definida",
    "elite100xpro": "Diapositiva en C-41: contraste extremo",
    "superia200xpro": "Proceso cruzado con luces amarillentas",
    "xproslide200": "Proceso cruzado de azules y amarillos",
    "tmax100": "Grano ultrafino y gradación suave",
    "tmax400": "B&N moderno, nítido y limpio",
    "tmax3200": "Ideal para forzar, noches con grano marcado",
    "bw400cn": "B&N cromogénico de grano muy fino",
    "hie": "Infrarrojo clásico: follaje blanco y cielos oscuros",
    "delta100": "B&N moderno muy fino y definido",
    "delta400": "Grano fino y suave a ISO 400",
    "delta3200": "Pensada para forzar en oscuridad",
    "fp4": "B&N clásico de sensibilidad media",
    "panf50": "Lenta, de grano prácticamente invisible",
    "hps800": "Ilford rápida clásica de reportaje",
    "xp2": "B&N revelado en C-41 de tonos suaves",
    "acros100": "Grano finísimo y negros profundos",
    "neopan1600": "B&N rápida de contraste marcado",
    "apx25": "Agfa B&N lenta de grano muy fino",
    "apx100": "B&N clásico de estética Agfa",
    "retro80s": "Sensible al rojo extendido, cielos oscuros",
    "retro100": "B&N de gradación tonal suave",
    "ortho25": "Ortocromática: los rojos se vuelven oscuros",
    "ir400": "Efecto infrarrojo con follaje luminoso",
    "kodak2383": "Copia de cine: sombras cian azuladas",
    "kodak2393": "Copia de cine con negros más densos",
    "fuji3510": "Película de proyección Fuji de color suave",
    "fuji3513": "Copia Fuji diseñada para máster digital",
}

CATEGORY_NAMES = {
    "neg": "Negativo Color (C-41)",
    "slide": "Diapositiva Color (E-6)",
    "cine": "Película de Cine",
    "bw": "Blanco y Negro",
    "xpro": "Proceso Cruzado",
    "print": "Copia Cinematográfica",
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
    "cinestill400d": dict(
        key="cinestill400d", brand="CineStill", name="CineStill 400D", iso=400, kind="cine", balance=5500, ev=0.0, sat=0.95,
        contrast=(0.175, 0.175, 0.168), pivot=(-0.05, 0.0, -0.05),
        black=(0.02, 0.03, 0.04), white=(0.97, 0.96, 0.95),
        hues=[("cyan", "blue", 0.1, 1.0), ("red", "orange", 0.08, 1.05)],
        halation=3.0, hal_thr=0.65, hal_tint=(1.0, 0.22, 0.05), grain=0.022, grain_size=1.3, soft=0.75,
        desc=DESCRIPTIONS.get("cinestill400d", "")
    ),
}

# Backward-compatible key aliases for historical saved recipes
FILM_ALIASES = {
    "cinestill400t": "cinestill400d",
}

# Append the remaining 63 stocks
for entry in STOCKS_DATA:
    key = entry[0]
    FILMS[key] = make_film(*entry)


def get_film(key):
    resolved = FILM_ALIASES.get(key, key)
    return FILMS.get(resolved, FILMS["portra400"])


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
