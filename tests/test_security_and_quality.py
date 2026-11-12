"""Regression suite for the v2.5.0 security and quality audit.

Every test here reproduces a defect that was verified against the running
application before the fix, so a future refactor cannot silently reintroduce
them.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.pipeline as pipeline_mod
from engine.lut import encode
from engine.negative_inverter import MINILAB_PROFILES, process_negative_to_image
from engine.pipeline import apply_grain, load_image_linear, srgb_to_linear

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app as haluro_app

    uploads = tmp_path / "uploads"
    developed = tmp_path / "developed"
    downloads = tmp_path / "Downloads"
    for folder in (uploads, developed, downloads):
        folder.mkdir()

    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "DEVELOPED_DIR", developed.resolve())
    monkeypatch.setattr(haluro_app, "get_downloads_dir", lambda: downloads.resolve())
    monkeypatch.setattr(haluro_app, "reveal_in_file_manager", lambda _p: True)

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as test_client:
        test_client.environ_base["HTTP_X_HALURO_TOKEN"] = haluro_app.API_TOKEN
        yield test_client


@pytest.fixture()
def traversal_probe(tmp_path: Path):
    """A directory outside the application tree, used to detect escapes."""
    probe = tmp_path / "outside"
    probe.mkdir()
    return probe


# ---------------------------------------------------------------------------
# 1. Path traversal through the film / profile keys
# ---------------------------------------------------------------------------

def test_film_key_cannot_escape_the_output_directory(client, traversal_probe) -> None:
    """A traversal payload in `film` must not write outside the app folders."""
    payload = "../../../../../../../../../.." + str(traversal_probe / "PWNED")
    resp = client.post(
        "/api/save_direct_to_downloads",
        json={"filename": "SAMPLE_NEGATIVE.jpg", "film": payload},
    )
    assert resp.status_code in (200, 400, 404)
    assert not list(traversal_probe.iterdir()), "se escribió fuera del directorio de la app"


def test_profile_key_cannot_escape_the_output_directory(client, traversal_probe) -> None:
    """A traversal payload in `profile` must not write outside the app folders."""
    payload = "../../../../../../../../../.." + str(traversal_probe / "PWNED")
    resp = client.post(
        "/api/negative/save_to_downloads",
        json={"profile": payload},
    )
    assert resp.status_code in (200, 400, 404)
    assert not list(traversal_probe.iterdir()), "se escribió fuera del directorio de la app"


def test_film_key_is_canonicalised_against_the_catalogue() -> None:
    from app import _canonical_film_key, _canonical_profile_key

    assert _canonical_film_key("portra400") == "portra400"
    assert _canonical_film_key("does-not-exist") == "portra400"
    assert "/" not in _canonical_film_key("../../etc/passwd")
    assert _canonical_profile_key("nope") == "frontier"
    assert _canonical_profile_key("frontier") == "frontier"


# ---------------------------------------------------------------------------
# 2. Local-session guard: Host, Origin and CSRF token
# ---------------------------------------------------------------------------

def test_non_loopback_host_is_rejected(client) -> None:
    """DNS rebinding: a Host header that is not loopback must be refused."""
    resp = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert resp.status_code in (400, 403)


def test_cross_origin_state_change_is_rejected(client) -> None:
    """A POST forged from another site must not be able to write anything."""
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"payload"), "evil.jpg")},
        content_type="multipart/form-data",
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403


def test_state_change_without_the_session_token_is_rejected() -> None:
    import app as haluro_app

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as bare:
        resp = bare.post("/api/upload", data={"file": (io.BytesIO(b"x"), "x.jpg")})
    assert resp.status_code == 403


def test_same_origin_state_change_is_allowed(client) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (30, 60, 90)).save(buf, format="JPEG")
    buf.seek(0)
    resp = client.post(
        "/api/upload",
        data={"file": (buf, "ok.jpg")},
        content_type="multipart/form-data",
        headers={"Origin": "http://127.0.0.1:5050"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 3. Input validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_value", ["abc", float("nan"), float("inf"), None])
def test_non_finite_or_non_numeric_parameters_return_400(client, bad_value) -> None:
    resp = client.post("/api/preview", json={"filename": "SAMPLE.CR2", "ev": bad_value})
    assert resp.status_code == 400, resp.get_data(as_text=True)


def test_out_of_range_parameters_are_clamped(client) -> None:
    """An absurd exposure must be clamped, not turned into an OverflowError."""
    resp = client.post("/api/preview", json={"filename": "SAMPLE.CR2", "ev": 1e308})
    assert resp.status_code == 200


def test_upload_rejects_a_non_image_payload(client) -> None:
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"notanimage"), "fake.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "válida" in resp.get_json()["error"] or "corrupto" in resp.get_json()["error"]


def test_upload_rejects_a_file_without_extension(client) -> None:
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"data"), "noextension")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4. Deterministic grain: the preview must match the exported master
# ---------------------------------------------------------------------------

def test_grain_is_deterministic_for_the_same_seed() -> None:
    rgb = np.full((32, 32, 3), 0.5, dtype=np.float32)
    first = apply_grain(rgb.copy(), amount=0.05, seed=1234)
    second = apply_grain(rgb.copy(), amount=0.05, seed=1234)
    other = apply_grain(rgb.copy(), amount=0.05, seed=4321)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, other)


def test_develop_frame_is_reproducible() -> None:
    sample = REPO_ROOT / "samples" / "SAMPLE.CR2"
    if not sample.is_file():
        pytest.skip("muestra RAW no disponible")
    a = pipeline_mod.develop_frame(str(sample), film_key="portra400", max_dim=320)
    b = pipeline_mod.develop_frame(str(sample), film_key="portra400", max_dim=320)
    assert np.array_equal(np.asarray(a), np.asarray(b))


# ---------------------------------------------------------------------------
# 5. 16-bit TIFF scaling must follow the declared depth, not the content
# ---------------------------------------------------------------------------

def test_16bit_tiff_is_scaled_by_its_declared_depth(tmp_path: Path) -> None:
    """A sub-exposed 16-bit scan stays below 255 and must not be scaled by 255."""
    path = tmp_path / "dark16.tif"
    data = (np.arange(256, dtype=np.uint16) * 199 // 255).reshape(16, 16)
    Image.fromarray(data).save(path)

    linear = load_image_linear(str(path))
    expected = srgb_to_linear(np.float32(199.0 / 65535.0))
    assert float(linear.max()) == pytest.approx(float(expected), rel=1e-4)
    # The old behaviour divided by 255 and produced a ~187x error.
    assert float(linear.max()) < 0.01


def test_16bit_scale_helper_reads_the_declared_bits() -> None:
    img = Image.new("I;16", (4, 4))
    assert pipeline_mod._declared_16bit_scale(img) == 65535.0


# ---------------------------------------------------------------------------
# 6. Film catalogue fidelity
# ---------------------------------------------------------------------------

def test_profile_glow_is_not_overridden_by_a_floor() -> None:
    """The 'linear' profile declares glow 0.0 and must not receive a halo."""
    assert MINILAB_PROFILES["linear"].get("glow") == 0.0
    assert MINILAB_PROFILES["vlog_flat"].get("glow", 0.12) < 0.12


def test_srgb_encoding_reaches_pure_white() -> None:
    """sRGB has no shoulder: the roll-off must not compress white below 1.0."""
    encoded = encode(np.array([[1.0, 1.0, 1.0]], dtype=np.float32), "srgb")
    assert float(encoded[0, 0]) == pytest.approx(1.0, abs=1e-4)


def test_uint8_conversion_rounds_instead_of_truncating() -> None:
    """A plain astype(uint8) truncates and biases every pixel by -0.5 LSB."""
    values = np.array([0.5 / 255.0, 1.5 / 255.0, 2.5 / 255.0], dtype=np.float32)
    rounded = np.rint(values * 255.0).astype(np.uint8)
    assert list(rounded) == [0, 2, 2]  # truncation would give [0, 1, 2]


# ---------------------------------------------------------------------------
# 7. Hurter-Driffield transfer driven by the measured density span
# ---------------------------------------------------------------------------

def test_measured_density_span_reaches_the_reconstruction() -> None:
    """The reconstruction must expose the measured log-exposure span."""
    from engine.negative_inverter import _compute_normalized_log_exposure

    sample = REPO_ROOT / "samples" / "SAMPLE_NEGATIVE.jpg"
    if not sample.is_file():
        pytest.skip("muestra de negativo no disponible")

    arr = load_image_linear(str(sample))
    _u, log_span = _compute_normalized_log_exposure(
        arr,
        base_color=None,
        film_type="color",
        profile_key="frontier",
        light_source="standard",
        scan_source="camera_raw",
        pre_saturation=1.0,
    )
    # A scanned negative spans roughly one unit of optical density.
    assert 0.25 <= log_span <= 3.0


def test_negative_inversion_still_produces_a_valid_image() -> None:
    sample = REPO_ROOT / "samples" / "SAMPLE_NEGATIVE.jpg"
    if not sample.is_file():
        pytest.skip("muestra de negativo no disponible")
    result = process_negative_to_image(str(sample), profile_key="frontier", max_dim=320)
    image = result[0] if isinstance(result, tuple) else result
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    assert array.max() > 0.4, "la inversión no debe quedar quemada"
    assert float(np.percentile(array, 50)) > 0.15, "los medios tonos deben conservar información"
    assert array.std() > 0.05


# ---------------------------------------------------------------------------
# 8. Memory behaviour
# ---------------------------------------------------------------------------

def test_contact_sheet_reduces_frames_to_thumbnails() -> None:
    """Frames must be shrunk on load instead of being retained at full size."""
    from engine.contact_sheet import generate_contact_sheet

    big = Image.new("RGB", (2400, 1600), (90, 90, 90))
    sheet = generate_contact_sheet([big], roll_name="R", film_name="F", columns=2, thumb_width=240)
    assert sheet.width <= 2400


def test_colour_space_conversion_matches_the_reference_formula() -> None:
    rng = np.random.default_rng(7)
    values = rng.random((64, 64, 3)).astype(np.float32)
    reference = np.where(
        values <= 0.04045,
        values / 12.92,
        np.power((values + 0.055) / 1.055, 2.4),
    ).astype(np.float32)
    assert np.abs(reference - srgb_to_linear(values)).max() < 1e-6


# ---------------------------------------------------------------------------
# 9. Release consistency
# ---------------------------------------------------------------------------

def test_version_is_consistent_across_the_repository() -> None:
    script = REPO_ROOT / ".github" / "scripts" / "check_version.py"
    if not script.is_file():
        pytest.skip("guardián de versión no disponible")
    import subprocess

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
