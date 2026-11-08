"""Fast 3D LUT loader and interpolator with color space transforms.
Supports .cube format (1D shaper + 3D mesh) with trilinear interpolation in NumPy.
"""

from pathlib import Path
import functools
import numpy as np

# Linear Rec.709 / sRGB primaries (D65) <-> ARRI Wide Gamut 3
_709_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                        [0.2126729, 0.7151522, 0.0721750],
                        [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)

_AWG3_TO_XYZ = np.array([[0.638008, 0.214704, 0.097744],
                         [0.291954, 0.823841, -0.115795],
                         [0.002798, -0.067034, 1.153294]], dtype=np.float32)

M_709_TO_AWG3 = (np.linalg.inv(_AWG3_TO_XYZ) @ _709_TO_XYZ).astype(np.float32)
M_AWG3_TO_709 = np.linalg.inv(M_709_TO_AWG3).astype(np.float32)

# Sony S-Gamut3.Cine (D65)
_SG3C_TO_XYZ = np.array([[0.5990839208, 0.2489255161, 0.1024464902],
                         [0.2150758201, 0.8850685017, -0.1001443219],
                         [-0.0320658495, -0.0276583907, 1.1487819910]], dtype=np.float32)
M_709_TO_SG3C = (np.linalg.inv(_SG3C_TO_XYZ) @ _709_TO_XYZ).astype(np.float32)

LOGC_CUT, LOGC_A, LOGC_B, LOGC_C = 0.010591, 5.555556, 0.052272, 0.247190
LOGC_D, LOGC_E, LOGC_F = 0.385537, 5.367655, 0.092809
CIN_BLACK = 10 ** ((95 - 685) * 0.002 / 0.6)
KNEE = 0.8


def _rolloff(x):
    x = np.maximum(x, 0)
    over = x - KNEE
    soft = KNEE + (1 - KNEE) * (1 - np.exp(-np.maximum(over, 0) / (1 - KNEE)))
    return np.where(over > 0, soft, x)


def _slog3(x):
    return np.where(x >= 0.01125,
                    (420 + np.log10(np.maximum(x + 0.01, 1e-6) / 0.19) * 261.5) / 1023,
                    (x * (171.2102946929 - 95) / 0.01125 + 95) / 1023)


def encode(lin, space="srgb"):
    """Convert scene-linear Rec.709 to the input space expected by the LUT."""
    lin = np.asarray(lin, np.float32)
    if space == "slog3":
        return _slog3(lin @ M_709_TO_SG3C.T)
    if space == "logc3":
        x = lin @ M_709_TO_AWG3.T
        return np.where(x > LOGC_CUT,
                        LOGC_C * np.log10(np.maximum(LOGC_A * x + LOGC_B, 1e-6)) + LOGC_D,
                        LOGC_E * x + LOGC_F)
    if space == "cineon":
        x = np.maximum(lin, 0) * (1 - CIN_BLACK) + CIN_BLACK
        return (685 + 300 * np.log10(np.maximum(x, 1e-6))) / 1023
    if space == "rec709":
        x = _rolloff(lin)
        return np.where(x < 0.018, 4.5 * x, 1.099 * np.power(np.maximum(x, 0), 0.45) - 0.099)
    if space == "srgb":
        x = _rolloff(lin)
        return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(np.maximum(x, 0), 1 / 2.4) - 0.055)
    if space == "linear":
        return lin
    return lin


def _trilinear(table, x):
    """Trilinear interpolation on a 3D table [B, G, R, 3] with query points x in [0, N-1]."""
    n = table.shape[0]
    flat = table.reshape(-1, 3)
    
    i = np.clip(np.floor(x).astype(np.int32), 0, n - 2)
    f = x - i
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    
    base = (i[..., 2] * n + i[..., 1]) * n + i[..., 0]
    
    def at(db, dg, dr):
        return flat[base + (db * n + dg) * n + dr]
        
    c00 = at(0, 0, 0) + (at(0, 0, 1) - at(0, 0, 0)) * fr
    c01 = at(0, 1, 0) + (at(0, 1, 1) - at(0, 1, 0)) * fr
    c10 = at(1, 0, 0) + (at(1, 0, 1) - at(1, 0, 0)) * fr
    c11 = at(1, 1, 0) + (at(1, 1, 1) - at(1, 1, 0)) * fr
    
    c0 = c00 + (c01 - c00) * fg
    c1 = c10 + (c11 - c10) * fg
    return c0 + (c1 - c0) * fb


class CubeLUT:
    def __init__(self, path, space="srgb"):
        self.path = Path(path)
        self.space = space
        size1 = size3 = 0
        self.domain_min = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.domain_max = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        rows = []
        
        with open(self.path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                key = parts[0].upper()
                if key == "LUT_1D_SIZE":
                    size1 = int(parts[1])
                elif key == "LUT_3D_SIZE":
                    size3 = int(parts[1])
                elif key == "DOMAIN_MIN" and len(parts) >= 4:
                    self.domain_min = np.array([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float32)
                elif key == "DOMAIN_MAX" and len(parts) >= 4:
                    self.domain_max = np.array([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float32)
                elif key[0].isdigit() or key[0] in "-+.":
                    rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    
        data = np.array(rows, dtype=np.float32)
        self.table1 = data[:size1] if size1 else None
        self.table3 = data[size1:].reshape(size3, size3, size3, 3) if size3 else None
        
    def _apply_1d(self, x):
        """Interpolate 1D shaper table per channel."""
        m = self.table1.shape[0]
        pos = np.clip(x, 0.0, 1.0) * (m - 1)
        idx = np.clip(np.floor(pos).astype(np.int32), 0, m - 2)
        frac = pos - idx
        out = np.empty_like(x, dtype=np.float32)
        for c in range(3):
            v0 = self.table1[idx[..., c], c]
            v1 = self.table1[idx[..., c] + 1, c]
            out[..., c] = v0 + (v1 - v0) * frac[..., c]
        return out

    def apply(self, lin_rgb, chunk=1000000):
        """Apply LUT to linear RGB image [H, W, 3], returning display sRGB [0..1]."""
        orig_shape = lin_rgb.shape
        flat = lin_rgb.reshape(-1, 3)
        out = np.empty_like(flat, dtype=np.float32)
        
        encoded = encode(flat, self.space)
        span = np.maximum(self.domain_max - self.domain_min, 1e-6)
        encoded = (encoded - self.domain_min) / span

        if self.table1 is not None:
            encoded = self._apply_1d(encoded)

        if self.table3 is None:
            return np.clip(encoded.reshape(orig_shape), 0.0, 1.0)

        n = self.table3.shape[0]
        
        for i in range(0, len(flat), chunk):
            sub = encoded[i:i + chunk]
            coords = np.clip(sub, 0.0, 1.0) * (n - 1)
            out[i:i + chunk] = _trilinear(self.table3, coords)
            
        return np.clip(out.reshape(orig_shape), 0.0, 1.0)


@functools.lru_cache(maxsize=32)
def load_lut(path, space="srgb"):
    return CubeLUT(path, space)
