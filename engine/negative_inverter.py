"""Negative Lab Engine (v2.3): Sensitometric Hurter-Driffield (H&D) inversion and
photochemical darkroom grading of digitized film negatives (DSLR/Mirrorless camera DNGs,
VueScan/SilverFast linear RAWs, flatbed TIFF/JPEG scans, and C-41 / B&W silver gelatin).

Implements:
- Spectrally agnostic maximum-transmittance D-min film base detection.
- Scan source pre-linearization (`camera_raw`, `scanner_raw`, `flatbed_tiff`) & optical dye `pre_saturation`.
- Unified Multi-Frame Roll Analysis (`analyze_roll_calibration`) & densitometric balance modes
  (`dynamic`, `shadow_weighted`, `roll_locked`).
- Photochemical darkroom media (`ra4_paper` C-Print, `cine_ecp` motion picture print,
  `vlog_flat` high-latitude log) & Minilab scanners (`frontier`, `noritsu`, `pakon`).
- Post-inversion Print Finishing layer (`PRINT_FINISHES`, continuous `0% - 200%` amount) &
  asymmetric shoulder/toe tone variants (`highlight_soft`, `shadow_soft`).
- B&W Silver-Gelatin chemical toners & fine-art papers (`BW_TONING_PROFILES`: Selenium #1-#3,
  Palladium, Sulfide Brown, Copper-Iron, Warmtone Foma, Cooltone, Cotton Rag Matte).
- 3-Way CMY Color Balance (`Shadows`, `Midtones`, `Highlights` + crossover ranges) &
  Hue-Invariant Color-Protected Clipping (`black_clip`, `white_clip`, `clip_protect`).
- Luminance-only grain-protected optical sharpening (`lab`, `scanner`) & 16-bit float export support.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image
import scipy.ndimage

from .pipeline import (
    apply_geometry,
    apply_optical_sharpen,
    linear_to_srgb,
    load_image_linear,
    shift_hues,
    srgb_to_linear,
)

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# Backlight dye-crosstalk compensation matrices applied in optical density space
LIGHT_SOURCE_MATRICES: dict[str, np.ndarray] = {
    # High-CRI White LED / Dedicated Film Scanner (6000K - 9000K)
    "standard": np.array(
        [
            [1.00, 0.00, 0.00],
            [0.00, 1.00, 0.00],
            [0.00, 0.00, 1.00],
        ],
        dtype=np.float32,
    ),
    # Narrow-band Cool Backlight (>9000K) / Direct Optical Print Light
    "cool": np.array(
        [
            [1.03, -0.02, -0.01],
            [-0.01, 1.02, -0.01],
            [0.00, -0.03, 1.03],
        ],
        dtype=np.float32,
    ),
    # Warm Household / Video LED Panel (<5500K) — decouples R-G bleed & blue starvation
    "warm": np.array(
        [
            [1.06, -0.05, -0.01],
            [-0.03, 1.05, -0.02],
            [0.02, -0.09, 1.07],
        ],
        dtype=np.float32,
    ),
}

# Input scan source pre-conditioning (compensates flatbed glass flare vs linear RAW)
SCAN_SOURCES: dict[str, dict[str, float | str]] = {
    "camera_raw": {
        "name": "Cámara RAW / DNG",
        "pre_gamma": 1.00,
        "pre_sat_bias": 1.00,
    },
    "scanner_raw": {
        "name": "Escáner RAW Lineal",
        "pre_gamma": 1.00,
        "pre_sat_bias": 1.06,
    },
    "flatbed_tiff": {
        "name": "Escáner Plano TIFF/JPG",
        "pre_gamma": 0.91,
        "pre_sat_bias": 1.15,
    },
}

COLOR_METHODS: set[str] = {"dynamic", "shadow_weighted", "roll_locked"}
SHARPEN_MODES: set[str] = {"off", "lab", "scanner"}

# (contrast_mult, sat_mult, hi_softness, sh_lift)
TONE_VARIANTS: dict[str, tuple[float, float, float, float]] = {
    "soft": (0.88, 0.95, 0.03, 0.03),
    "standard": (1.00, 1.00, 0.00, 0.00),
    "vivid": (1.15, 1.08, 0.00, 0.00),
    "highlight_soft": (0.98, 1.00, 0.09, 0.00),
    "shadow_soft": (0.97, 1.00, 0.00, 0.08),
}


def linear_rgb_to_hex(lin_rgb) -> str:
    """Convert a 3-element linear RGB [0..1] color to perceptual sRGB #RRGGBB hex."""
    arr = np.array(lin_rgb, dtype=np.float32)
    if arr.max() > 1.5:
        srgb = np.clip(arr / 255.0, 0.0, 1.0)
    else:
        srgb = linear_to_srgb(np.clip(arr, 0.0, 1.0))
    r, g, b = [int(np.clip(round(float(c) * 255.0), 0, 255)) for c in srgb[:3]]
    return f"#{r:02X}{g:02X}{b:02X}"


MINILAB_PROFILES = {
    "ra4_paper": {
        "name": "Papel Cuarto Oscuro RA-4",
        "chip": "C-Print",
        "desc": "Curva fotoquímica de papel cromogénico con verdes orgánicos y pieles naturales.",
        "gamma": 1.01,
        "contrast": 1.13,
        "toe": 0.012,
        "shoulder": 0.988,
        "sat": 1.05,
        "cmy_bias": (0.015, -0.005, -0.012),
        "glow": 0.12,
        "fade": 0.004,
        "hue_rules": [
            ("yellow", "orange", 0.14, 1.02),
            ("green", "cyan", 0.18, 0.95),
            ("cyan", "blue", -0.12, 0.94),
            ("blue", "cyan", 0.08, 0.93),
        ],
    },
    "cine_ecp": {
        "name": "Copia de Cine ECP 2383",
        "chip": "CinePrint",
        "desc": "Estética de proyección cinematográfica: negros densos de sala y separación cálido-fría.",
        "gamma": 1.07,
        "contrast": 1.22,
        "toe": 0.018,
        "shoulder": 0.986,
        "sat": 1.09,
        "cmy_bias": (0.022, -0.008, -0.020),
        "shadows_bias": (-0.016, 0.004, 0.020),
        "glow": 0.16,
        "fade": 0.0,
        "hue_rules": [
            ("yellow", "orange", 0.16, 1.03),
            ("blue", "cyan", 0.16, 0.96),
        ],
    },
    "frontier": {
        "name": "Fuji Frontier SP-3000",
        "chip": "Clásico",
        "desc": "Contraste vivo, tonos de piel cálidos dorados y altas luces luminosas.",
        "gamma": 1.04,
        "contrast": 1.18,
        "toe": 0.015,
        "shoulder": 0.985,
        "sat": 1.12,
        "cmy_bias": (0.03, -0.01, -0.02),
        "glow": 0.18,
        "fade": 0.0,
    },
    "noritsu": {
        "name": "Noritsu HS-1800",
        "chip": "Suave",
        "desc": "Sombras pastel abiertas, latitud amplia y transición delicada en altas luces.",
        "gamma": 0.94,
        "contrast": 1.04,
        "toe": 0.0,
        "shoulder": 0.99,
        "sat": 1.02,
        "cmy_bias": (0.01, 0.0, 0.01),
        "glow": 0.10,
        "fade": 0.018,
    },
    "pakon": {
        "name": "Pakon F135 Plus",
        "chip": "Vibrante",
        "desc": "Estética editorial de los 90, saturación profunda y contraste marcado.",
        "gamma": 1.10,
        "contrast": 1.28,
        "toe": 0.02,
        "shoulder": 0.98,
        "sat": 1.24,
        "cmy_bias": (0.02, 0.01, -0.03),
        "glow": 0.22,
        "fade": 0.0,
    },
    "vlog_flat": {
        "name": "Logarítmico Latitud (V-Log)",
        "chip": "Latitud",
        "desc": "Inversión plana de rango extendido para películas de alto contraste, caducadas o cruzadas.",
        "gamma": 0.89,
        "contrast": 0.82,
        "toe": -0.015,
        "shoulder": 1.015,
        "sat": 0.94,
        "cmy_bias": (0.0, 0.0, 0.0),
        "glow": 0.04,
        "fade": 0.008,
    },
    "linear": {
        "name": "Lineal Plano",
        "chip": "Neutro",
        "desc": "Inversión sensitométrica pura sin curva de contraste añadida; rango dinámico íntegro.",
        "gamma": 1.0,
        "contrast": 1.0,
        "toe": 0.0,
        "shoulder": 1.0,
        "sat": 1.0,
        "cmy_bias": (0.0, 0.0, 0.0),
        "glow": 0.0,
        "fade": 0.0,
    },
    "bw": {
        "name": "Gelatina de Plata B&N",
        "chip": "Monocromo",
        "desc": "Inversión densitométrica monocroma con soporte para virados químicos y papeles de arte.",
        "gamma": 1.06,
        "contrast": 1.16,
        "toe": 0.015,
        "shoulder": 0.985,
        "sat": 0.0,
        "cmy_bias": (0.0, 0.0, 0.0),
        "glow": 0.08,
        "fade": 0.01,
    },
}

# Post-inversion Print / Stock Finishing Grades (scalable continuously 0% - 200%)
PRINT_FINISHES: dict[str, dict] = {
    "none": {
        "name": "Sin acabado extra",
        "desc": "Fidelidad pura al medio fotoquímico o escáner seleccionado.",
        "contrast": 1.0,
        "mid_lift": 0.0,
        "sat": 1.0,
        "fade": 0.0,
        "sh_rgb": (0.0, 0.0, 0.0),
        "mid_rgb": (0.0, 0.0, 0.0),
        "hi_rgb": (0.0, 0.0, 0.0),
        "hue_rules": None,
    },
    "crystal_archive": {
        "name": "Fuji Crystal Archive",
        "desc": "Blancos puros de galería, verdes esmeralda limpios y negros profundos de papel RC.",
        "contrast": 1.07,
        "mid_lift": 0.01,
        "sat": 1.06,
        "fade": 0.0,
        "sh_rgb": (-0.008, 0.002, 0.010),
        "mid_rgb": (0.004, 0.002, -0.006),
        "hi_rgb": (0.006, 0.003, -0.004),
        "hue_rules": [
            ("green", "cyan", 0.20, 0.96),
            ("yellow", "orange", 0.12, 1.03),
        ],
    },
    "portra_airy": {
        "name": "Portra Airy Pastel",
        "desc": "Medios tonos luminosos, pieles melocotón suaves y altas luces aireadas.",
        "contrast": 0.94,
        "mid_lift": 0.055,
        "sat": 0.97,
        "fade": 0.012,
        "sh_rgb": (0.004, 0.002, 0.006),
        "mid_rgb": (0.014, 0.004, -0.012),
        "hi_rgb": (0.018, 0.008, -0.014),
        "hue_rules": [
            ("red", "orange", 0.14, 0.96),
            ("cyan", "blue", -0.10, 0.94),
        ],
    },
    "gold_warm": {
        "name": "Gold Cálido Dorado",
        "desc": "Calidez solar nostálgica en luces, ámbar rico y sombras azul cobalto sutil.",
        "contrast": 1.06,
        "mid_lift": 0.015,
        "sat": 1.11,
        "fade": 0.005,
        "sh_rgb": (-0.010, -0.003, 0.014),
        "mid_rgb": (0.022, 0.008, -0.024),
        "hi_rgb": (0.026, 0.014, -0.028),
        "hue_rules": [
            ("yellow", "orange", 0.22, 1.06),
        ],
    },
    "superia_cool": {
        "name": "Superia Esmeralda",
        "desc": "Estética japonesa clásica con sombras verde-cian y magentas vibrantes.",
        "contrast": 1.08,
        "mid_lift": 0.0,
        "sat": 1.08,
        "fade": 0.004,
        "sh_rgb": (-0.018, 0.014, 0.008),
        "mid_rgb": (-0.006, 0.005, 0.004),
        "hi_rgb": (0.012, -0.004, -0.004),
        "hue_rules": [
            ("green", "cyan", 0.24, 1.04),
        ],
    },
    "cine_halation": {
        "name": "Cine Tungsteno / Halación",
        "desc": "Separación nocturna teal-ámbar con resplandor cálido en luces especulares.",
        "contrast": 1.10,
        "mid_lift": -0.01,
        "sat": 1.07,
        "fade": 0.006,
        "sh_rgb": (-0.024, 0.006, 0.026),
        "mid_rgb": (0.006, 0.0, -0.006),
        "hi_rgb": (0.032, 0.006, -0.024),
        "halation": 0.35,
        "hue_rules": [
            ("blue", "cyan", 0.18, 1.02),
        ],
    },
    "portrait_soft": {
        "name": "Retrato Editorial Suave",
        "desc": "Transición sedosa de baja dureza para retrato con piso mate delicado.",
        "contrast": 0.91,
        "mid_lift": 0.035,
        "sat": 0.94,
        "fade": 0.020,
        "sh_rgb": (0.008, 0.002, -0.004),
        "mid_rgb": (0.012, 0.004, -0.010),
        "hi_rgb": (0.010, 0.005, -0.008),
        "hue_rules": None,
    },
    "clean_contrast": {
        "name": "Contraste Limpio Estudio",
        "desc": "Grises neutros calibrados y micro-contraste firme sin dominantes.",
        "contrast": 1.14,
        "mid_lift": -0.01,
        "sat": 1.03,
        "fade": 0.0,
        "sh_rgb": (0.0, 0.0, 0.0),
        "mid_rgb": (0.0, 0.0, 0.0),
        "hi_rgb": (0.0, 0.0, 0.0),
        "hue_rules": None,
    },
}

# Silver-Gelatin B&W Chemical Toners & Fine-Art Darkroom Papers
BW_TONING_PROFILES: dict[str, dict] = {
    "neutral": {
        "name": "Plata Neutra Pura",
        "chip": "Neutro",
        "desc": "Copia monocroma densitométrica sin virado químico (R = G = B).",
        "dmax_boost": 0.0,
        "contrast_mult": 1.0,
        "paper_fade": 0.0,
        "sh_rgb": (0.0, 0.0, 0.0),
        "mid_rgb": (0.0, 0.0, 0.0),
        "paper_white": (1.0, 1.0, 1.0),
    },
    "selenium_1": {
        "name": "Selenio #1 (Archivo)",
        "chip": "D-Max+",
        "desc": "Baño breve de selenio: refuerza el negro máximo con matiz frío casi imperceptible.",
        "dmax_boost": 0.04,
        "contrast_mult": 1.03,
        "paper_fade": 0.0,
        "sh_rgb": (0.009, -0.006, 0.012),
        "mid_rgb": (0.003, -0.002, 0.004),
        "paper_white": (1.0, 0.999, 0.996),
    },
    "selenium_2": {
        "name": "Selenio #2 (Galería)",
        "chip": "Clásico",
        "desc": "Virado clásico de exposición: sombras berenjena-plata profundas y luces limpias.",
        "dmax_boost": 0.075,
        "contrast_mult": 1.06,
        "paper_fade": 0.0,
        "sh_rgb": (0.020, -0.011, 0.024),
        "mid_rgb": (0.008, -0.004, 0.009),
        "paper_white": (1.0, 0.998, 0.994),
    },
    "selenium_3": {
        "name": "Selenio #3 (Profundo)",
        "chip": "Intenso",
        "desc": "Inmersión prolongada en selenio con riqueza púrpura-cacao en sombras densas.",
        "dmax_boost": 0.105,
        "contrast_mult": 1.09,
        "paper_fade": 0.0,
        "sh_rgb": (0.034, -0.016, 0.035),
        "mid_rgb": (0.015, -0.007, 0.014),
        "paper_white": (1.0, 0.996, 0.990),
    },
    "palladium": {
        "name": "Platinotipia / Paladio",
        "chip": "Noble",
        "desc": "Escala tonal extensa de metales nobles, negros aterciopelados y medios tonos cálidos.",
        "dmax_boost": 0.0,
        "contrast_mult": 0.92,
        "paper_fade": 0.022,
        "sh_rgb": (0.018, 0.006, -0.020),
        "mid_rgb": (0.028, 0.010, -0.030),
        "paper_white": (1.0, 0.986, 0.958),
    },
    "sepia_sulfide": {
        "name": "Sepia Sulfuro / Kodak Brown",
        "chip": "Sulfuro",
        "desc": "Virador de polisulfuro cálido de archivo con sombras tierra y luces marfil.",
        "dmax_boost": 0.025,
        "contrast_mult": 1.02,
        "paper_fade": 0.008,
        "sh_rgb": (0.045, 0.013, -0.048),
        "mid_rgb": (0.056, 0.020, -0.062),
        "paper_white": (1.0, 0.980, 0.938),
    },
    "copper_iron": {
        "name": "Cobre y Hierro (Split)",
        "chip": "Bicolor",
        "desc": "Doble baño químico: sombras azul de Prusia frío y medios/altos cobrizos cálidos.",
        "dmax_boost": 0.04,
        "contrast_mult": 1.04,
        "paper_fade": 0.005,
        "sh_rgb": (-0.030, -0.002, 0.038),
        "mid_rgb": (0.030, 0.007, -0.028),
        "paper_white": (1.0, 0.988, 0.968),
    },
    "warmtone_foma": {
        "name": "Clorobromuro (Fomatone)",
        "chip": "Cálido",
        "desc": "Emulsión de clorobromuro de plata con negros oliva-cálidos y soporte crema.",
        "dmax_boost": 0.03,
        "contrast_mult": 1.02,
        "paper_fade": 0.006,
        "sh_rgb": (0.024, 0.013, -0.030),
        "mid_rgb": (0.022, 0.010, -0.026),
        "paper_white": (1.0, 0.989, 0.962),
    },
    "cooltone": {
        "name": "Bromuro Frío (Cooltone)",
        "chip": "Acero",
        "desc": "Papel bromuro de tono frío metálico con sombras azul-acero y blanco brillante.",
        "dmax_boost": 0.05,
        "contrast_mult": 1.05,
        "paper_fade": 0.0,
        "sh_rgb": (-0.018, -0.002, 0.026),
        "mid_rgb": (-0.010, 0.0, 0.015),
        "paper_white": (0.988, 0.996, 1.0),
    },
    "cotton_matte": {
        "name": "Algodón Mate Museo",
        "chip": "Fine-Art",
        "desc": "Papel 100% algodón sin blanqueadores ópticos y piso mate suave de museo.",
        "dmax_boost": 0.0,
        "contrast_mult": 0.95,
        "paper_fade": 0.032,
        "sh_rgb": (0.012, 0.005, -0.014),
        "mid_rgb": (0.014, 0.006, -0.016),
        "paper_white": (1.0, 0.985, 0.952),
    },
}


def list_profiles() -> list[dict[str, str]]:
    return [
        {
            "key": k,
            "name": v["name"],
            "chip": v.get("chip", ""),
            "desc": v["desc"],
        }
        for k, v in MINILAB_PROFILES.items()
    ]


def list_print_finishes() -> list[dict[str, str]]:
    return [
        {"key": k, "name": v["name"], "desc": v["desc"]}
        for k, v in PRINT_FINISHES.items()
    ]


def list_bw_toners() -> list[dict[str, str]]:
    return [
        {"key": k, "name": v["name"], "chip": v["chip"], "desc": v["desc"]}
        for k, v in BW_TONING_PROFILES.items()
    ]


def auto_detect_film_base(lin_img, buffer_pct: float = 0.02) -> list[float]:
    """Auto-detect the unexposed film base mask (D-min) in linear RGB [0..1]."""
    arr = np.asarray(lin_img, dtype=np.float32)
    h, w = arr.shape[:2]
    by = max(1, int(h * buffer_pct))
    bx = max(1, int(w * buffer_pct))

    region = arr[by : h - by, bx : w - bx] if (h > 2 * by + 8 and w > 2 * bx + 8) else arr

    not_clipped_white = np.min(region, axis=-1) < 0.94
    not_holder_black = np.max(region, axis=-1) > 0.012
    valid_mask = not_clipped_white & not_holder_black
    valid = region[valid_mask] if np.any(valid_mask) else region.reshape(-1, 3)

    r = np.maximum(valid[:, 0], 1e-6)
    g = np.maximum(valid[:, 1], 1e-6)
    b = np.maximum(valid[:, 2], 1e-6)
    geom_trans = np.cbrt(r * g * b)
    mean_trans = (r + g + b) * (1.0 / 3.0)
    transmittance_score = 0.55 * geom_trans + 0.45 * mean_trans

    threshold = np.percentile(transmittance_score, 98.5)
    top_pixels = valid[transmittance_score >= threshold]
    if len(top_pixels) > 0:
        base_color = np.median(top_pixels, axis=0)
    else:
        base_color = np.percentile(valid, 98.5, axis=0)

    return np.clip(base_color, 0.015, 1.0).tolist()


def _raw_optical_density(
    lin_img: np.ndarray,
    base_color,
    is_bw: bool,
    light_source: str,
    scan_source: str,
    pre_saturation: float,
) -> np.ndarray:
    """Compute pre-conditioned, dye-decoupled Hurter-Driffield optical density array D >= 0."""
    arr = np.asarray(lin_img, dtype=np.float32)
    src_cfg = SCAN_SOURCES.get(scan_source, SCAN_SOURCES["camera_raw"])
    pre_gamma = float(src_cfg["pre_gamma"])
    pre_sat_bias = float(src_cfg["pre_sat_bias"])

    if abs(pre_gamma - 1.0) > 1e-3:
        arr = np.power(np.maximum(arr, 1e-6), pre_gamma)

    base_raw = np.array(base_color, dtype=np.float32)
    if base_raw.max() > 1.5:
        base_raw = srgb_to_linear(np.clip(base_raw / 255.0, 0.0, 1.0))
    if abs(pre_gamma - 1.0) > 1e-3:
        base_raw = np.power(np.maximum(base_raw, 1e-6), pre_gamma)
    base = np.maximum(base_raw[None, None, :], 1e-4)

    if is_bw:
        luma_val = np.sum(arr * LUMA, axis=-1, keepdims=True)
        arr = np.repeat(luma_val, 3, axis=-1)
        base = np.repeat(np.sum(base * LUMA, axis=-1, keepdims=True), 3, axis=-1)

    norm = np.clip(arr / base, 1e-4, 1.6)
    density = -np.log10(np.clip(norm, 1e-4, 2.0)).astype(np.float32)

    if not is_bw and light_source in LIGHT_SOURCE_MATRICES and light_source != "standard":
        mtx = LIGHT_SOURCE_MATRICES[light_source]
        density = np.tensordot(density, mtx.T, axes=1).astype(np.float32)

    return density


def analyze_roll_calibration(
    linear_frames: list[np.ndarray],
    film_type: str = "color",
    light_source: str = "standard",
    scan_source: str = "camera_raw",
    pre_saturation: float = 1.0,
    border_buffer: float = 0.06,
) -> dict:
    """Compute unified roll-wide D-min base color and optical density envelope across multiple frames."""
    if not linear_frames:
        raise ValueError("No se proporcionaron fotogramas para analizar el rollo.")

    is_bw = film_type == "bw"
    per_frame_bases = [auto_detect_film_base(f) for f in linear_frames]
    # Use the highest-transmittance (75th percentile across roll) D-min so dark night frames don't skew base
    bases_arr = np.array(per_frame_bases, dtype=np.float32)
    unified_base = np.percentile(bases_arr, 75.0, axis=0).tolist()

    sampled_densities: list[np.ndarray] = []
    buf_p = float(np.clip(border_buffer, 0.0, 0.30))
    rng = np.random.default_rng(1972)

    for frame in linear_frames:
        d = _raw_optical_density(
            frame,
            base_color=unified_base,
            is_bw=is_bw,
            light_source=light_source,
            scan_source=scan_source,
            pre_saturation=pre_saturation,
        )
        h, w = d.shape[:2]
        by, bx = int(h * buf_p), int(w * buf_p)
        reg = d[by : h - by, bx : w - bx] if (h - 2 * by > 16 and w - 2 * bx > 16) else d
        flat = reg.reshape(-1, 3)
        if len(flat) > 12000:
            idx = rng.choice(len(flat), size=12000, replace=False)
            flat = flat[idx]
        sampled_densities.append(flat)

    all_d = np.concatenate(sampled_densities, axis=0)
    roll_d_min = np.percentile(all_d, 0.8, axis=0)
    roll_d_max = np.percentile(all_d, 99.4, axis=0)
    # Ensure non-degenerate dynamic range
    roll_d_max = np.maximum(roll_d_max, roll_d_min + 0.10)

    return {
        "base_color": [round(float(c), 5) for c in unified_base],
        "base_hex": linear_rgb_to_hex(unified_base),
        "roll_d_min": [round(float(c), 5) for c in roll_d_min],
        "roll_d_max": [round(float(c), 5) for c in roll_d_max],
        "frames_analyzed": len(linear_frames),
    }


def _normalized_scurve(u: np.ndarray, slope: float) -> np.ndarray:
    """Symmetric normalized logistic S-curve on [0..1] centered at 0.5."""
    if abs(slope - 1.0) < 0.015:
        return u
    if slope > 1.0:
        k = (slope - 1.0) * 6.5 + 0.5
        s0 = 1.0 / (1.0 + np.exp(k * 0.5))
        s1 = 1.0 / (1.0 + np.exp(-k * 0.5))
        s = 1.0 / (1.0 + np.exp(-k * (u - 0.5)))
        return np.clip((s - s0) / max(s1 - s0, 1e-5), 0.0, 1.0)
    amount = float(np.clip(slope, 0.35, 1.0))
    return np.clip(0.5 + (u - 0.5) * amount, 0.0, 1.0)


def _color_protected_clip(u: np.ndarray, b_clip: float, w_clip: float, protect_chroma: bool = True) -> np.ndarray:
    """Map [b_clip .. w_clip] to [0 .. 1] while preserving hue angle in bright highlights & deep shadows."""
    span = max(float(w_clip - b_clip), 0.10)
    mapped = (u - float(b_clip)) / span

    if not protect_chroma:
        return np.clip(mapped, 0.0, 1.0)

    # Soft hue-preserving shoulder above 0.88 so single-channel clipping doesn't skew skin/sky to yellow/cyan
    y = np.sum(mapped * LUMA, axis=-1, keepdims=True)
    max_c = np.max(mapped, axis=-1, keepdims=True)
    shoulder_start = 0.88
    over = np.maximum(0.0, max_c - shoulder_start)
    # Asymptotic soft roll-off mapping [0.88 .. inf) -> [0.88 .. 1.0]
    compressed_max = np.where(
        max_c > shoulder_start,
        shoulder_start + (1.0 - shoulder_start) * (1.0 - np.exp(-over / max(1.0 - shoulder_start, 1e-4))),
        max_c,
    )
    scale_hi = np.where(max_c > shoulder_start, compressed_max / np.maximum(max_c, 1e-5), 1.0)
    y_soft = np.clip(y * scale_hi, 0.0, 1.0)
    chroma_diff = (mapped - y) * scale_hi
    out = y_soft + chroma_diff

    # Similarly damp out-of-gamut negative excursions smoothly near 0.0
    min_c = np.min(out, axis=-1, keepdims=True)
    under_mask = (min_c < 0.0) & (y_soft > 1e-4)
    if np.any(under_mask):
        safe_scale_lo = np.where(under_mask, y_soft / np.maximum(y_soft - min_c, 1e-5), 1.0)
        out = y_soft + (out - y_soft) * np.clip(safe_scale_lo, 0.0, 1.0)

    return np.clip(out, 0.0, 1.0)


def _apply_cmy_zone_offset(
    pos: np.ndarray,
    weight: np.ndarray,
    cmy_triplet,
    scale: float,
) -> np.ndarray:
    """Apply luminance-conserving CMY offset [Cyan↔Red, Magenta↔Green, Yellow↔Blue] weighted by tonal zone."""
    cr = float(cmy_triplet[0]) if len(cmy_triplet) > 0 else 0.0
    mg = float(cmy_triplet[1]) if len(cmy_triplet) > 1 else 0.0
    yb = float(cmy_triplet[2]) if len(cmy_triplet) > 2 else 0.0
    if abs(cr) < 0.003 and abs(mg) < 0.003 and abs(yb) < 0.003:
        return pos

    # Luminance-balanced RGB basis vectors for Red-Cyan, Green-Magenta, Blue-Yellow
    dr = cr * 1.00 - mg * 0.35 - yb * 0.42
    dg = -cr * 0.32 + mg * 0.88 - yb * 0.38
    db = -cr * 0.42 - mg * 0.35 + yb * 1.00

    w = weight[..., 0] if weight.ndim == 3 else weight
    pos[..., 0] += w * (dr * scale)
    pos[..., 1] += w * (dg * scale)
    pos[..., 2] += w * (db * scale)
    return pos


def _compute_normalized_log_exposure(
    lin_img: np.ndarray,
    base_color=None,
    film_type: str = "color",
    profile_key: str = "frontier",
    light_source: str = "standard",
    scan_source: str = "camera_raw",
    pre_saturation: float = 1.0,
    color_method: str = "dynamic",
    roll_bounds: dict | None = None,
    border_buffer: float = 0.06,
    crop_pct: float = 0.0,
) -> np.ndarray:
    """Convert negative linear RGB into cropped normalized H&D log-exposure `u` in [0..1]."""
    arr = np.asarray(lin_img, dtype=np.float32)
    h, w = arr.shape[:2]

    if base_color is None:
        base_color = auto_detect_film_base(arr)

    is_bw = film_type == "bw" or profile_key == "bw"
    density = _raw_optical_density(
        arr,
        base_color=base_color,
        is_bw=is_bw,
        light_source=light_source,
        scan_source=scan_source,
        pre_saturation=pre_saturation,
    )

    buf_p = float(np.clip(border_buffer, 0.0, 0.30))
    by = int(h * buf_p)
    bx = int(w * buf_p)
    if h - 2 * by > 16 and w - 2 * bx > 16:
        analysis_region = density[by : h - by, bx : w - bx]
    else:
        analysis_region = density

    # Densitometric White/Black Point Method
    if (
        color_method == "roll_locked"
        and isinstance(roll_bounds, dict)
        and "d_min" in roll_bounds
        and "d_max" in roll_bounds
    ):
        d_min = np.array(roll_bounds["d_min"], dtype=np.float32)
        d_max = np.array(roll_bounds["d_max"], dtype=np.float32)
        d_range = np.maximum(d_max - d_min, 0.08)
    elif color_method == "shadow_weighted" and not is_bw:
        # Anchor black point strictly on shadow floor & damp per-channel highlight range divergence
        # so scenes dominated by blue ocean, foliage, or sunset don't invert with opposite color cast
        d_min = np.percentile(analysis_region, 0.5, axis=(0, 1))
        d_max_raw = np.percentile(analysis_region, 99.4, axis=(0, 1))
        raw_span = np.maximum(d_max_raw - d_min, 0.08)
        median_span = float(np.median(raw_span))
        d_range = raw_span * 0.38 + median_span * 0.62
    else:
        d_min = np.percentile(analysis_region, 0.8, axis=(0, 1))
        d_max = np.percentile(analysis_region, 99.4, axis=(0, 1))
        d_range = np.maximum(d_max - d_min, 0.08)

    u = np.clip((density - d_min) / d_range, 0.0, 1.0)

    # Optical Pre-Saturation in normalized H&D log-exposure space (preserves neutral gray axis
    # and cannot be cancelled out by per-channel dynamic endpoint normalization)
    src_cfg = SCAN_SOURCES.get(scan_source, SCAN_SOURCES["camera_raw"])
    total_pre_sat = float(np.clip(pre_saturation, 0.4, 1.8)) * float(src_cfg["pre_sat_bias"])
    if not is_bw and abs(total_pre_sat - 1.0) > 0.008:
        u_mean = np.sum(u * LUMA, axis=-1, keepdims=True)
        u = np.clip(u_mean + (u - u_mean) * total_pre_sat, 0.0, 1.0)

    c_p = float(np.clip(crop_pct, 0.0, 0.20))
    if c_p > 0.002:
        cy = int(h * c_p)
        cx = int(w * c_p)
        if h - 2 * cy > 32 and w - 2 * cx > 32:
            u = u[cy : h - cy, cx : w - cx]

    return u


def compute_neutral_wb_from_point(
    lin_img: np.ndarray,
    x_pct: float,
    y_pct: float,
    base_color=None,
    film_type: str = "color",
    profile_key: str = "frontier",
    light_source: str = "standard",
    scan_source: str = "camera_raw",
    pre_saturation: float = 1.0,
    color_method: str = "dynamic",
    roll_bounds: dict | None = None,
    border_buffer: float = 0.06,
    crop_pct: float = 0.0,
    temp: float = 0.0,
    tint: float = 0.0,
) -> list[float]:
    """Solve closed-form CMY printer lights to neutralize a sampled gray/shadow point in positive space."""
    if film_type == "bw" or profile_key == "bw":
        return [0.0, 0.0, 0.0]

    u = _compute_normalized_log_exposure(
        lin_img,
        base_color=base_color,
        film_type=film_type,
        profile_key=profile_key,
        light_source=light_source,
        scan_source=scan_source,
        pre_saturation=pre_saturation,
        color_method=color_method,
        roll_bounds=roll_bounds,
        border_buffer=border_buffer,
        crop_pct=crop_pct,
    )
    uh, uw = u.shape[:2]
    px = int(np.clip(round(float(x_pct) * (uw - 1)), 0, uw - 1))
    py = int(np.clip(round(float(y_pct) * (uh - 1)), 0, uh - 1))

    patch = u[max(0, py - 3) : min(uh, py + 4), max(0, px - 3) : min(uw, px + 4)]
    u_rgb = np.median(patch.reshape(-1, 3), axis=0)
    u_safe = np.clip(u_rgb, 0.06, 0.94)
    u_target = float(np.mean(u_safe))

    profile = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])
    b_cr, b_mg, b_yb = profile.get("cmy_bias", (0.0, 0.0, 0.0))

    req_gain_r = u_target / float(u_safe[0])
    req_gain_g = u_target / float(u_safe[1])
    req_gain_b = u_target / float(u_safe[2])

    cmy_r = ((req_gain_r - 1.0 - float(temp) * 0.20) / 0.28) - b_cr
    cmy_g = ((1.0 - req_gain_g - float(tint) * 0.20) / 0.28) - b_mg
    cmy_b = ((1.0 - req_gain_b - float(temp) * 0.20) / 0.28) - b_yb

    return [round(float(np.clip(v, -1.0, 1.0)), 3) for v in (cmy_r, cmy_g, cmy_b)]


def auto_balance_scene_wb(
    lin_img: np.ndarray,
    base_color=None,
    film_type: str = "color",
    profile_key: str = "frontier",
    light_source: str = "standard",
    scan_source: str = "camera_raw",
    pre_saturation: float = 1.0,
    color_method: str = "dynamic",
    roll_bounds: dict | None = None,
    border_buffer: float = 0.06,
    crop_pct: float = 0.0,
) -> list[float]:
    """Automatically estimate CMY printer lights for borderless scans using midtone Gray-World."""
    if film_type == "bw" or profile_key == "bw":
        return [0.0, 0.0, 0.0]

    u = _compute_normalized_log_exposure(
        lin_img,
        base_color=base_color,
        film_type=film_type,
        profile_key=profile_key,
        light_source=light_source,
        scan_source=scan_source,
        pre_saturation=pre_saturation,
        color_method=color_method,
        roll_bounds=roll_bounds,
        border_buffer=border_buffer,
        crop_pct=crop_pct,
    )
    uh, uw = u.shape[:2]
    my, mx = int(uh * 0.08), int(uw * 0.08)
    core = u[my : uh - my, mx : uw - mx] if (uh > 2 * my + 8 and uw > 2 * mx + 8) else u

    u_luma = np.sum(core * LUMA, axis=-1)
    mid_mask = (u_luma >= 0.16) & (u_luma <= 0.82)
    sample_pixels = core[mid_mask] if np.count_nonzero(mid_mask) >= 64 else core.reshape(-1, 3)

    ch_means = np.clip(np.mean(sample_pixels, axis=0), 0.08, 0.92)
    target = float(np.mean(ch_means))
    blended = ch_means + (target - ch_means) * 0.65

    profile = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])
    b_cr, b_mg, b_yb = profile.get("cmy_bias", (0.0, 0.0, 0.0))

    req_gain_r = float(blended[0] / ch_means[0])
    req_gain_g = float(blended[1] / ch_means[1])
    req_gain_b = float(blended[2] / ch_means[2])

    cmy_r = ((req_gain_r - 1.0) / 0.28) - b_cr
    cmy_g = ((1.0 - req_gain_g) / 0.28) - b_mg
    cmy_b = ((1.0 - req_gain_b) / 0.28) - b_yb

    return [round(float(np.clip(v, -1.0, 1.0)), 3) for v in (cmy_r, cmy_g, cmy_b)]


def _apply_print_finish(pos: np.ndarray, finish_key: str, amount: float, frame_w: int) -> np.ndarray:
    """Apply optional post-inversion Print / Emulsion Finishing Grade at 0% - 200% intensity."""
    if not finish_key or finish_key == "none" or amount <= 0.01:
        return pos
    fin = PRINT_FINISHES.get(finish_key)
    if not fin:
        return pos

    amt = float(np.clip(amount, 0.0, 2.0))
    # Work in perceptual sRGB-like gamma for natural paper tonal/color response, then return to linear
    s = linear_to_srgb(pos)

    if abs(fin["mid_lift"]) > 0.001:
        y0 = np.maximum(np.sum(s * LUMA, axis=-1, keepdims=True), 1e-5)
        exp_m = float(2.0 ** (-fin["mid_lift"] * amt * 1.4))
        s = np.clip(s * (np.power(np.clip(y0, 0.0, 1.0), exp_m) / y0), 0.0, 1.0)

    c_slope = 1.0 + (fin["contrast"] - 1.0) * amt
    if abs(c_slope - 1.0) > 0.01:
        s = _normalized_scurve(s, c_slope)

    y_zone = np.sum(s * LUMA, axis=-1, keepdims=True)
    sh_w = np.clip(1.0 - y_zone / 0.55, 0.0, 1.0) ** 1.5
    hi_w = np.clip((y_zone - 0.45) / 0.55, 0.0, 1.0) ** 1.5
    mid_w = np.clip(1.0 - np.abs(y_zone - 0.50) * 2.1, 0.0, 1.0)

    for c in range(3):
        s[..., c] += (
            sh_w[..., 0] * fin["sh_rgb"][c]
            + mid_w[..., 0] * fin["mid_rgb"][c]
            + hi_w[..., 0] * fin["hi_rgb"][c]
        ) * amt

    if fin["fade"] > 0.001:
        f_amt = min(0.12, fin["fade"] * amt)
        s = s * (1.0 - f_amt) + f_amt * 0.85

    s = np.clip(s, 0.0, 1.0)
    if fin.get("hue_rules"):
        scaled_rules = [
            (f_h, t_h, h_amt * min(amt, 1.5), 1.0 + (ch_m - 1.0) * min(amt, 1.5))
            for (f_h, t_h, h_amt, ch_m) in fin["hue_rules"]
        ]
        s = shift_hues(s, scaled_rules)

    sat_f = 1.0 + (fin["sat"] - 1.0) * amt
    if abs(sat_f - 1.0) > 0.005:
        ys = np.sum(s * LUMA, axis=-1, keepdims=True)
        s = np.clip(ys + (s - ys) * sat_f, 0.0, 1.0)

    out_lin = srgb_to_linear(s)
    hal = float(fin.get("halation", 0.0)) * amt
    if hal > 0.01:
        l_lin = np.sum(out_lin * LUMA, axis=-1)
        over = np.maximum(0.0, l_lin - 0.66)
        glow = scipy.ndimage.gaussian_filter(over, sigma=max(2.0, frame_w * 0.008))
        out_lin = np.clip(
            out_lin + glow[..., None] * np.array([1.0, 0.26, 0.06], dtype=np.float32) * (hal * 0.35),
            0.0,
            1.0,
        )
    return out_lin


def _apply_bw_darkroom_toning(
    y_lin: np.ndarray,
    toner_key: str,
    strength: float,
    shadows_tint=(0.0, 0.0, 0.0),
    mids_tint=(0.0, 0.0, 0.0),
    highs_tint=(0.0, 0.0, 0.0),
    shadows_range: float = 0.5,
    highs_range: float = 0.5,
) -> np.ndarray:
    """Apply silver-gelatin chemical toning & fine-art paper base tint in B&W darkroom mode."""
    toner = BW_TONING_PROFILES.get(toner_key, BW_TONING_PROFILES["neutral"])
    amt = float(np.clip(strength, 0.0, 1.5))

    has_user_3way = any(
        abs(float(v)) > 0.004
        for trip in (shadows_tint, mids_tint, highs_tint)
        for v in (trip or (0.0, 0.0, 0.0))
    )
    if (toner_key == "neutral" or amt <= 0.005) and not has_user_3way:
        return np.clip(np.repeat(y_lin, 3, axis=-1), 0.0, 1.0)

    # Convert monochrome luminance to perceptual sRGB domain for darkroom paper density curve & chemical dye toning
    s_mono = linear_to_srgb(np.clip(y_lin, 0.0, 1.0))

    if toner_key != "neutral" and amt > 0.005:
        c_mult = 1.0 + (toner["contrast_mult"] - 1.0) * min(amt, 1.25)
        if abs(c_mult - 1.0) > 0.008:
            s_mono = _normalized_scurve(s_mono, c_mult)

        dmax = toner["dmax_boost"] * amt
        if dmax > 0.002:
            toe_zone = np.clip((0.45 - s_mono) / 0.45, 0.0, 1.0) ** 1.6
            s_mono = np.clip(s_mono - toe_zone * dmax, 0.0, 1.0)

        p_fade = toner["paper_fade"] * amt
        if p_fade > 0.001:
            s_mono = s_mono * (1.0 - p_fade) + p_fade * 0.85

    rgb_s = np.repeat(s_mono, 3, axis=-1)

    if toner_key != "neutral" and amt > 0.005:
        sh_w = (np.clip(1.0 - s_mono / 0.58, 0.0, 1.0) ** 1.45) * (0.25 + 0.75 * np.clip(s_mono / 0.08, 0.0, 1.0))
        mid_w = np.clip(1.0 - np.abs(s_mono - 0.48) * 2.1, 0.0, 1.0)
        for c in range(3):
            rgb_s[..., c] += (sh_w[..., 0] * toner["sh_rgb"][c] + mid_w[..., 0] * toner["mid_rgb"][c]) * amt
            pw = 1.0 + (toner["paper_white"][c] - 1.0) * min(amt, 1.2)
            rgb_s[..., c] *= pw

    if has_user_3way:
        sh_pivot = 0.25 + float(np.clip(shadows_range, 0.0, 1.0)) * 0.42
        hi_pivot = 0.75 - float(np.clip(highs_range, 0.0, 1.0)) * 0.40
        sh_u = np.clip((sh_pivot - s_mono) / max(sh_pivot, 0.10), 0.0, 1.0) ** 1.4
        hi_u = np.clip((s_mono - hi_pivot) / max(1.0 - hi_pivot, 0.10), 0.0, 1.0) ** 1.4
        mid_u = np.clip(1.0 - np.abs(s_mono - 0.50) * 2.0, 0.0, 1.0)
        rgb_s = _apply_cmy_zone_offset(rgb_s, sh_u, shadows_tint, 0.11)
        rgb_s = _apply_cmy_zone_offset(rgb_s, mid_u, mids_tint, 0.10)
        rgb_s = _apply_cmy_zone_offset(rgb_s, hi_u, highs_tint, 0.11)

    return srgb_to_linear(np.clip(rgb_s, 0.0, 1.0))


def invert_negative(
    lin_img,
    base_color=None,
    film_type="color",
    profile_key="frontier",
    light_source="standard",
    scan_source="camera_raw",
    pre_saturation=1.0,
    color_method="dynamic",
    roll_bounds=None,
    tone_variant="standard",
    print_finish="none",
    finish_amount=1.0,
    bw_toner="neutral",
    bw_toner_strength=1.0,
    brightness=0.0,
    midtone_nd=0.0,
    contrast=0.0,
    push_pull=0.0,
    lights=0.0,
    darks=0.0,
    whites=0.0,
    blacks=0.0,
    black_clip=0.0,
    white_clip=0.0,
    clip_protect=True,
    inky_blacks=0.0,
    sat_mult=1.0,
    rp_tone=0.0,
    border_buffer=0.06,
    crop_pct=0.0,
    glow_mult=1.0,
    fade_mult=1.0,
    printer_cyan_red=0.0,
    printer_magenta_green=0.0,
    printer_yellow_blue=0.0,
    temp=0.0,
    tint=0.0,
    warming_85=0.0,
    skylight_filter=0.0,
    shade_filter=0.0,
    highs_tint=(0.0, 0.0, 0.0),
    mids_tint=(0.0, 0.0, 0.0),
    shadows_tint=(0.0, 0.0, 0.0),
    shadows_range=0.5,
    highs_range=0.5,
):
    """Sensitometric H&D inversion of a digitized negative into scene-linear positive RGB [0..1]."""
    profile = MINILAB_PROFILES.get(profile_key, MINILAB_PROFILES["frontier"])
    is_bw = film_type == "bw" or profile_key == "bw"

    # 1 & 2. Base subtraction, source pre-conditioning, backlight decoupling, D-min/D-max & border crop
    u = _compute_normalized_log_exposure(
        lin_img,
        base_color=base_color,
        film_type=film_type,
        profile_key=profile_key,
        light_source=light_source,
        scan_source=scan_source,
        pre_saturation=pre_saturation,
        color_method=color_method,
        roll_bounds=roll_bounds,
        border_buffer=border_buffer,
        crop_pct=crop_pct,
    )
    h, w = u.shape[:2]

    # 3. Enlarger Printer Lights (CMY), WB & Optical Warming 85B Filter
    b_cr, b_mg, b_yb = profile.get("cmy_bias", (0.0, 0.0, 0.0))
    w85 = 0.0 if is_bw else float(np.clip(warming_85, 0.0, 1.0))
    gain_r = 1.0 + (printer_cyan_red + b_cr) * 0.28 + temp * 0.20 + w85 * 0.14
    gain_g = 1.0 - (printer_magenta_green + b_mg) * 0.28 - tint * 0.20 + w85 * 0.03
    gain_b = 1.0 - (printer_yellow_blue + b_yb) * 0.28 - temp * 0.20 - w85 * 0.15

    u[..., 0] = np.clip(u[..., 0] * gain_r, 0.0, 1.25)
    u[..., 1] = np.clip(u[..., 1] * gain_g, 0.0, 1.25)
    u[..., 2] = np.clip(u[..., 2] * gain_b, 0.0, 1.25)

    # Optional Optical Skylight (Highlight Red-Cast Suppressor) & Shade (Green Base-Fog Suppressor)
    if not is_bw:
        sky = float(np.clip(skylight_filter, 0.0, 1.0))
        shd = float(np.clip(shade_filter, 0.0, 1.0))
        if sky > 0.005 or shd > 0.005:
            u_lum0 = np.sum(np.clip(u, 0.0, 1.0) * LUMA, axis=-1)
            if sky > 0.005:
                hi_zone = np.clip((u_lum0 - 0.42) / 0.58, 0.0, 1.0) ** 1.3
                u[..., 0] -= hi_zone * (sky * 0.09)
                u[..., 1] += hi_zone * (sky * 0.025)
                u[..., 2] += hi_zone * (sky * 0.035)
            if shd > 0.005:
                lo_zone = np.clip((0.48 - u_lum0) / 0.48, 0.0, 1.0) ** 1.3
                u[..., 1] -= lo_zone * (shd * 0.09)
                u[..., 0] += lo_zone * (shd * 0.035)
                u[..., 2] += lo_zone * (shd * 0.035)
        if light_source == "warm":
            u_lum_w = np.sum(np.clip(u, 0.0, 1.0) * LUMA, axis=-1)
            hi_w = np.clip((u_lum_w - 0.50) / 0.50, 0.0, 1.0) ** 1.4
            u[..., 0] -= hi_w * 0.03

    # 4. Brightness (Gamma) & Color-Neutral Midtone Density (`midtone_nd`)
    gamma_user = max(0.30, profile["gamma"] * (1.0 - brightness * 0.42))
    u = np.power(np.clip(u, 0.0, 1.25), gamma_user)
    u = np.clip(u, 0.0, 1.0)

    if abs(midtone_nd) > 0.005:
        y_u = np.maximum(np.sum(u * LUMA, axis=-1, keepdims=True), 1e-5)
        nd_exp = float(2.0 ** (-float(np.clip(midtone_nd, -1.0, 1.0)) * 0.55))
        y_nd = np.power(np.clip(y_u, 0.0, 1.0), nd_exp)
        u = np.clip(u * (y_nd / y_u), 0.0, 1.0)

    # 5. Tone Variant (`soft` / `standard` / `vivid` / `highlight_soft` / `shadow_soft`), S-Curve & Push/Pull
    variant_c_mult, variant_s_mult, var_hi_soft, var_sh_lift = TONE_VARIANTS.get(
        tone_variant, TONE_VARIANTS["standard"]
    )
    pp = float(np.clip(push_pull, -1.0, 1.0))
    pp_contrast_mult = 1.0 + pp * 0.24

    total_contrast = max(
        0.35,
        profile["contrast"] * variant_c_mult * pp_contrast_mult * (1.0 + contrast * 0.45),
    )
    u = _normalized_scurve(u, total_contrast)

    if var_hi_soft > 0.001 or var_sh_lift > 0.001:
        u_lv = np.sum(u * LUMA, axis=-1, keepdims=True)
        if var_hi_soft > 0.001:
            hm = np.clip((u_lv - 0.45) / 0.55, 0.0, 1.0) ** 1.4
            u = np.clip(u - var_hi_soft * hm, 0.0, 1.0)
        if var_sh_lift > 0.001:
            sm = np.clip((0.55 - u_lv) / 0.55, 0.0, 1.0) ** 1.4
            u = np.clip(u + var_sh_lift * sm, 0.0, 1.0)

    if abs(pp) > 0.005:
        u_lum_pp = np.sum(u * LUMA, axis=-1, keepdims=True)
        if pp < 0.0:
            pull_amt = -pp
            sh_lift = np.clip((0.50 - u_lum_pp) / 0.50, 0.0, 1.0) ** 1.5
            hi_recover = np.clip((u_lum_pp - 0.50) / 0.50, 0.0, 1.0) ** 1.5
            u = np.clip(u + pull_amt * 0.09 * sh_lift - pull_amt * 0.07 * hi_recover, 0.0, 1.0)

    # 6. Highlights, Shadows, Whites, Blacks, Anti-Fog `Inky Blacks` & Color-Protected Clipping
    u_luma = np.sum(u * LUMA, axis=-1, keepdims=True)
    if abs(lights) > 0.005:
        high_mask = np.clip((u_luma - 0.35) / 0.65, 0.0, 1.0) ** 1.4
        u = u + lights * 0.22 * high_mask
    if abs(darks) > 0.005:
        dark_mask = np.clip((0.65 - u_luma) / 0.65, 0.0, 1.0) ** 1.4
        u = u + darks * 0.22 * dark_mask

    inky = float(np.clip(inky_blacks, 0.0, 1.0))
    if inky > 0.005:
        fog_zone = np.clip((0.38 - u) / 0.38, 0.0, 1.0) ** 1.75
        u = np.clip(u - fog_zone * (inky * 0.14), 0.0, 1.0)

    bc_off = float(np.clip(black_clip, -0.5, 0.5)) * 0.14
    wc_off = float(np.clip(white_clip, -0.5, 0.5)) * 0.14
    b_clip_val = profile["toe"] - blacks * 0.12 + (inky * 0.025) + bc_off
    w_clip_val = profile["shoulder"] - whites * 0.12 - wc_off
    u = _color_protected_clip(u, b_clip_val, w_clip_val, protect_chroma=bool(clip_protect) and not is_bw)

    # 7. Reconstruct scene-linear positive light from perceptual log-density u
    pos = np.power(u, 2.15)

    # Photochemical RA-4 / CinePrint ECP selective hue calibration
    hue_rules = profile.get("hue_rules")
    if hue_rules and not is_bw:
        pos_srgb = linear_to_srgb(pos)
        pos_srgb = shift_hues(pos_srgb, hue_rules)
        pos = srgb_to_linear(pos_srgb)

    # 8. LabGlow (Optical Enlarger Diffusion / Highlight Bloom in linear light)
    base_glow = max(0.12, profile.get("glow", 0.12))
    glow_strength = base_glow * float(np.clip(glow_mult, 0.0, 3.0))
    if glow_strength > 0.01:
        luma_lin = np.sum(pos * LUMA, axis=-1)
        highs = np.maximum(0.0, luma_lin - 0.40) ** 1.3
        glow_blur = scipy.ndimage.gaussian_filter(highs, sigma=max(3.0, w * 0.014))
        pos = pos + glow_blur[..., None] * (glow_strength * 0.55)

    # 9. LabFade (Matte Paper Black Floor)
    base_fade = profile.get("fade", 0.0)
    f_mult = float(np.clip(fade_mult, 0.0, 3.0))
    if f_mult <= 1.0:
        fade_strength = base_fade * f_mult
    else:
        fade_strength = base_fade + 0.030 * (f_mult - 1.0)

    if fade_strength > 0.001:
        pos = pos * (1.0 - fade_strength) + (fade_strength * 0.40)

    # 10. B&W Silver-Gelatin Chemical Toning & Fine-Art Paper Branch
    if is_bw:
        y = np.sum(np.clip(pos, 0.0, 1.0) * LUMA, axis=-1, keepdims=True)
        return _apply_bw_darkroom_toning(
            y,
            toner_key=str(bw_toner or "neutral"),
            strength=float(bw_toner_strength),
            shadows_tint=shadows_tint,
            mids_tint=mids_tint,
            highs_tint=highs_tint,
            shadows_range=float(shadows_range),
            highs_range=float(highs_range),
        )

    # 11. 3-Way CMY Split-Toning (`Shadows` · `Midtones` · `Highlights`) + Profile Bias
    prof_sb = profile.get("shadows_bias", (0.0, 0.0, 0.0))
    if any(abs(v) > 0.002 for v in prof_sb):
        luma_sb = np.sum(np.clip(pos, 0.0, 1.0) * LUMA, axis=-1, keepdims=True)
        sb_w = np.clip(1.0 - luma_sb, 0.0, 1.0) ** 2.0
        pos[..., 0] += sb_w[..., 0] * (prof_sb[0] * 0.10)
        pos[..., 1] += sb_w[..., 0] * (prof_sb[1] * 0.10)
        pos[..., 2] += sb_w[..., 0] * (prof_sb[2] * 0.10)
        pos = np.clip(pos, 0.0, 1.0)

    has_3way = any(
        abs(float(v)) > 0.004
        for trip in (shadows_tint, mids_tint, highs_tint)
        for v in (trip or (0.0, 0.0, 0.0))
    )
    if has_3way:
        s_pos = linear_to_srgb(np.clip(pos, 0.0, 1.0))
        y_s = np.sum(s_pos * LUMA, axis=-1, keepdims=True)
        sh_pivot = 0.25 + float(np.clip(shadows_range, 0.0, 1.0)) * 0.42
        hi_pivot = 0.75 - float(np.clip(highs_range, 0.0, 1.0)) * 0.40

        sh_w = (np.clip((sh_pivot - y_s) / max(sh_pivot, 0.10), 0.0, 1.0) ** 1.4) * (
            0.25 + 0.75 * np.clip(y_s / 0.12, 0.0, 1.0)
        )
        hi_w = (np.clip((y_s - hi_pivot) / max(1.0 - hi_pivot, 0.10), 0.0, 1.0) ** 1.4) * (
            0.35 + 0.65 * np.clip((1.0 - y_s) / 0.08, 0.0, 1.0)
        )
        mid_w = np.clip(1.0 - np.abs(y_s - 0.50) * 2.0, 0.0, 1.0)

        s_pos = _apply_cmy_zone_offset(s_pos, sh_w, shadows_tint, 0.12)
        s_pos = _apply_cmy_zone_offset(s_pos, mid_w, mids_tint, 0.11)
        s_pos = _apply_cmy_zone_offset(s_pos, hi_w, highs_tint, 0.12)
        pos = srgb_to_linear(np.clip(s_pos, 0.0, 1.0))

    # 12. Optional Post-Inversion Print / Emulsion Finishing Grade (`0% - 200%`)
    if print_finish and print_finish != "none" and float(finish_amount) > 0.01:
        pos = _apply_print_finish(pos, str(print_finish), float(finish_amount), w)

    # 13. RP Tone (Neutral-Protected Analog Vibrance) & Chromatic Saturation Calibration
    rp = float(np.clip(rp_tone, 0.0, 1.0))
    sat_factor = profile["sat"] * variant_s_mult * float(sat_mult)

    if rp > 0.005 or abs(sat_factor - 1.0) > 0.005:
        y = np.sum(pos * LUMA, axis=-1, keepdims=True)
        diff = pos - y
        if rp > 0.005:
            chroma = np.max(pos, axis=-1, keepdims=True) - np.min(pos, axis=-1, keepdims=True)
            neutral_gate = np.clip((chroma - 0.018) / 0.075, 0.0, 1.0)
            headroom = 1.0 - np.clip(chroma, 0.0, 1.0) * 0.65
            rp_gain = 1.0 + rp * 0.68 * neutral_gate * headroom
            diff = diff * rp_gain
        pos = np.clip(y + diff * sat_factor, 0.0, 1.0)

    return np.clip(pos, 0.0, 1.0)


def process_negative_to_image(
    image_input,
    max_dim=None,
    rotate=0,
    flip_h=False,
    sharpen_mode="off",
    sharpen_amount=1.0,
    return_float=False,
    **kwargs,
):
    """Process a digitized negative into a positive display-sRGB PIL Image (and optional float32 sRGB)."""
    if isinstance(image_input, (str, Path)):
        lin = load_image_linear(image_input, max_dim=max_dim, rotate=rotate, flip_h=flip_h)
    elif isinstance(image_input, Image.Image):
        if max_dim is not None and max(image_input.size) > max_dim:
            scale = max_dim / max(image_input.size)
            new_size = (int(image_input.width * scale), int(image_input.height * scale))
            image_input = image_input.resize(new_size, Image.Resampling.LANCZOS)
        lin = srgb_to_linear(np.asarray(image_input, dtype=np.float32) / 255.0)
        if rotate or flip_h:
            lin = apply_geometry(lin, rotate=rotate, flip_h=flip_h)
    else:
        lin = np.array(image_input, dtype=np.float32)
        if rotate or flip_h:
            lin = apply_geometry(lin, rotate=rotate, flip_h=flip_h)

    pos = invert_negative(lin, **kwargs)
    srgb = linear_to_srgb(pos)
    if sharpen_mode and sharpen_mode != "off" and float(sharpen_amount) > 0.01:
        srgb = apply_optical_sharpen(srgb, mode=str(sharpen_mode), amount=float(sharpen_amount))

    srgb_clamped = np.clip(srgb, 0.0, 1.0).astype(np.float32)
    pil_img = Image.fromarray((srgb_clamped * 255.0).astype(np.uint8))
    if return_float:
        return pil_img, srgb_clamped
    return pil_img
