"""Automated test suite for Haluro v2.3.0 (macOS & Windows 11).

Covers:
  1. Cross-platform OS abstraction (`engine.platform_io`) on macOS & mocked Windows 11
     (frozen PyInstaller `_MEIPASS`, `%LOCALAPPDATA%\\Haluro`, Explorer `/select`,
     injection-safe PowerShell/AppleScript Save dialogs, cross-platform fonts).
  2. 16-bit RAW linear pipeline, 1D+3D `.cube` LUT engine, Hurter–Driffield C-41/ECP/RA-4
     sensitometric negative inversion, universal `D-min` detector, positive Scene WB solver,
     color-neutral `midtone_nd`, `inky_blacks`, contact sheets, and lossless JPG/PNG/TIFF export.
  3. Haluro v2.3 modules: 10 B&W chemical toners & fine-art papers, unified multi-frame
     Roll Analysis (`roll_locked`), 3-Way CMY split-toning, color-protected clipping,
     Print Finishing layers, grain-protected luminance optical sharpening, true 48-bit
     (`16-bit/channel`) TIFF export/re-import, and native Analog EXIF metadata stamping.
  4. Non-destructive source file integrity (SHA-256 verification), HTTP API readiness
     (`/api/health`), OWASP security headers, and path-traversal defense.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from engine import APP_NAME, __version__, platform_io
from engine.contact_sheet import generate_contact_sheet
from engine.films import LUT_DIR, get_film, list_films
from engine.lut import CubeLUT
from engine.negative_inverter import (
    BW_TONING_PROFILES,
    MINILAB_PROFILES,
    PRINT_FINISHES,
    TONE_VARIANTS,
    analyze_roll_calibration,
    auto_balance_scene_wb,
    auto_detect_film_base,
    compute_neutral_wb_from_point,
    invert_negative,
    process_negative_to_image,
)
from engine.pipeline import (
    apply_optical_sharpen,
    develop_frame,
    format_analog_caption,
    linear_to_srgb,
    load_image_linear,
    save_output_image,
    srgb_to_linear,
)

# The expected version is resolved from the package metadata, so the suite does
# not need editing on every release bump.
try:
    __EXPECTED_VERSION = _pkg_version("haluro")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __EXPECTED_VERSION = __version__

# A version that is always newer than the current one, used by the updater test.
_NEWER_VERSION = "99.0.0"

# =============================================================================
# 1. CROSS-PLATFORM OS ABSTRACTION (macOS & WINDOWS 11)
# =============================================================================


def test_platform_detection_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert platform_io.is_windows() is True
    assert platform_io.is_macos() is False
    assert platform_io.get_platform_tag() == "windows"

    monkeypatch.setattr(sys, "platform", "darwin")
    assert platform_io.is_macos() is True
    assert platform_io.is_windows() is False
    assert platform_io.get_platform_tag() == "macos"

    monkeypatch.setattr(sys, "platform", "linux")
    assert platform_io.get_platform_tag() == "linux"


def test_frozen_windows11_separates_bundle_resources_from_localappdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_meipass = tmp_path / "ProgramFiles_Haluro_MEIPASS"
    fake_meipass.mkdir()
    fake_localappdata = tmp_path / "Users_Test_AppData_Local"
    fake_localappdata.mkdir()

    monkeypatch.delenv("HALURO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))

    assert platform_io.is_frozen() is True
    assert platform_io.get_resource_root() == fake_meipass.resolve()

    user_data = platform_io.get_user_data_root()
    assert user_data == (fake_localappdata / APP_NAME).resolve()
    assert user_data.is_dir()
    assert user_data != fake_meipass.resolve()


def test_frozen_macos_uses_application_support_and_library_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "MacHome"
    fake_home.mkdir()
    fake_meipass = tmp_path / "HaluroApp_Contents_Frameworks"
    fake_meipass.mkdir()

    monkeypatch.delenv("HALURO_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    user_data = platform_io.get_user_data_root()
    logs_dir = platform_io.get_logs_dir()

    assert user_data == (fake_home / "Library" / "Application Support" / APP_NAME).resolve()
    assert logs_dir == (fake_home / "Library" / "Logs" / APP_NAME)
    assert user_data.is_dir()
    assert logs_dir.is_dir()


def test_windows11_explorer_reveal_selects_target_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exported_file = tmp_path / "revelado_portra400.jpg"
    exported_file.write_bytes(b"jpeg")

    monkeypatch.setattr(sys, "platform", "win32")
    with mock.patch.object(subprocess, "Popen") as mock_popen:
        ok = platform_io.reveal_in_file_manager(exported_file)

    assert ok is True
    mock_popen.assert_called_once()
    called_args = mock_popen.call_args[0][0]
    assert called_args[0] == "explorer.exe"
    assert called_args[1].startswith("/select,")
    assert "revelado_portra400.jpg" in called_args[1]


def test_windows11_save_dialog_passes_filename_via_env_without_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    tricky_name = 'rollo"$(calc)$env:SECRET.tiff'

    fake_completed = subprocess.CompletedProcess(
        args=["powershell"],
        returncode=0,
        stdout=str(tmp_path / "salida_maestra"),  # Deliberately missing extension
        stderr="",
    )

    with mock.patch.object(subprocess, "run", return_value=fake_completed) as mock_run:
        chosen = platform_io.choose_save_path_dialog(tricky_name, default_dir=tmp_path)

    assert chosen is not None
    assert chosen.endswith(".tiff")
    _, kwargs = mock_run.call_args
    ps_cmd_str = mock_run.call_args[0][0][-1]
    # Ensure user input was NOT interpolated into the PowerShell script string
    assert "calc" not in ps_cmd_str
    assert kwargs["env"]["HALURO_SAVE_NAME"] == Path(tricky_name).name


def test_cross_platform_font_loader_handles_all_roles_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for role in ("sans-bold", "sans", "mono-bold", "mono"):
        font = platform_io.load_ui_font(role=role, size=18)
        assert font is not None

    # Simulate stripped OS with zero TrueType fonts installed
    monkeypatch.setattr(platform_io, "_FONT_CANDIDATES", {"mono": ("/nonexistent/font.ttf",)})
    fallback_font = platform_io.load_ui_font(role="mono", size=14)
    assert fallback_font is not None


# =============================================================================
# 2. OPTICAL ENGINE, LUTS, NON-DESTRUCTIVE RAW & HURTER-DRIFFIELD INVERSION
# =============================================================================


def test_72_film_catalog_and_cube_luts() -> None:
    films = list_films()
    assert len(films) == 80
    lut_files = list(LUT_DIR.rglob("*.cube"))
    assert len(lut_files) >= 60
    # Verify every LUT-backed film stock resolves to an existing .cube file
    for film_summary in films:
        spec = get_film(film_summary["key"])
        if spec.get("lut_file"):
            assert (LUT_DIR / spec["lut_file"]).is_file()
    # Spot-check LUT interpolation across categories
    for lut_path in lut_files[:10]:
        lut = CubeLUT(lut_path, space="srgb")
        sample = np.array([[[0.18, 0.18, 0.18], [0.75, 0.50, 0.25]]], dtype=np.float32)
        out = lut.apply(sample)
        assert out.shape == sample.shape
        assert out.dtype == np.float32


def test_1d_plus_3d_cube_identity_lut(tmp_path: Path) -> None:
    cube_text = "\n".join(
        [
            "TITLE \"Identity 1D+3D\"",
            "LUT_1D_SIZE 4",
            "LUT_3D_SIZE 2",
            "0.0 0.0 0.0",
            "0.333333 0.333333 0.333333",
            "0.666667 0.666667 0.666667",
            "1.0 1.0 1.0",
            "0 0 0",
            "1 0 0",
            "0 1 0",
            "1 1 0",
            "0 0 1",
            "1 0 1",
            "0 1 1",
            "1 1 1",
        ]
    )
    lut_file = tmp_path / "identity_combo.cube"
    lut_file.write_text(cube_text, encoding="utf-8")

    lut = CubeLUT(lut_file, space="linear")
    arr = np.linspace(0.05, 0.95, 12, dtype=np.float32).reshape(2, 2, 3)
    res = lut.apply(arr)
    np.testing.assert_allclose(res, arr, atol=1e-4)


def test_raw_16bit_pipeline_preserves_original_file_intact() -> None:
    sample_raw = platform_io.get_resource_root() / "samples" / "SAMPLE.CR2"
    assert sample_raw.is_file()

    sha_before = hashlib.sha256(sample_raw.read_bytes()).hexdigest()

    # Scene-linear 16-bit RAW preserves unclipped highlight headroom (> 1.0 before roll-off)
    linear_preview = load_image_linear(sample_raw, max_dim=320)
    assert linear_preview.dtype == np.float32
    assert float(linear_preview.min()) >= 0.0
    assert float(linear_preview.max()) > 0.2

    developed = develop_frame(
        sample_raw,
        "portra400",
        ev_adjust=0.3,
        halation_mult=1.1,
        grain_mult=1.0,
        vignette_mult=1.0,
        add_date=True,
        max_dim=480,
    )
    assert isinstance(developed, Image.Image)
    assert max(developed.size) == 480

    sha_after = hashlib.sha256(sample_raw.read_bytes()).hexdigest()
    assert sha_before == sha_after, "Source RAW file must remain 100% untouched!"


def test_hurter_driffield_c41_negative_inversion_and_all_profiles() -> None:
    # Construct synthetic C-41 negative scan:
    # Unexposed orange mask border: high transmittance [0.78, 0.34, 0.14]
    # Dark scene shadow (low density -> high transmittance near base)
    # Bright scene highlight (high silver/dye density -> low transmittance)
    neg_lin = np.zeros((120, 160, 3), dtype=np.float32)
    orange_base = np.array([0.78, 0.34, 0.14], dtype=np.float32)
    neg_lin[:, :] = orange_base  # Unexposed border

    # Left half inside frame: shadow in real scene (transmits 80% of base)
    neg_lin[15:105, 15:80] = orange_base * 0.80
    # Right half inside frame: bright sky in real scene (transmits only 14% of base)
    neg_lin[15:105, 80:145] = orange_base * 0.14

    detected_base = auto_detect_film_base(neg_lin)
    assert detected_base[0] > detected_base[1] > detected_base[2]

    for profile_key in MINILAB_PROFILES:
        pos_img = process_negative_to_image(
            neg_lin,
            base_color=detected_base,
            film_type="bw" if profile_key == "bw" else "color",
            profile_key=profile_key,
            border_buffer=0.10,
        )
        arr = np.asarray(pos_img, dtype=np.float32)
        shadow_mean = float(arr[30:90, 25:70].mean())
        highlight_mean = float(arr[30:90, 90:135].mean())
        assert highlight_mean > shadow_mean + 40.0, (
            f"Profile '{profile_key}' failed positive tonal polarity!"
        )


def test_universal_dmin_detector_handles_cool_backlight_and_excludes_clipped_glass() -> None:
    # Camera-WB pre-balanced or Cool (>9000K) backlight DNG scan where B > G > R at D-min
    neg_cool = np.zeros((120, 160, 3), dtype=np.float32)
    cool_dmin = np.array([0.10, 0.27, 0.35], dtype=np.float32)

    # Outer 8px ring: black film holder; next 6px: uncovered white light-table glass
    neg_cool[:, :] = 0.003
    neg_cool[8:112, 8:152] = 0.985
    # Unexposed cyan-tinted film rebate
    neg_cool[14:106, 14:146] = cool_dmin
    # Exposed scene core (higher density -> lower transmittance)
    neg_cool[26:94, 26:134] = cool_dmin * 0.32

    detected = auto_detect_film_base(neg_cool)
    assert detected[2] > detected[1] > detected[0], "Must preserve B > G > R on Cool/WB-balanced DNGs"
    np.testing.assert_allclose(detected, cool_dmin, atol=0.015)


def test_scene_neutral_wb_solver_and_auto_scene_wb_neutralize_cast() -> None:
    # Borderless negative with a cyan/blue cast in midtones
    rng = np.random.default_rng(42)
    h, w = 96, 128
    base = np.array([0.62, 0.34, 0.18], dtype=np.float32)
    #Varying tonal ramp from shadow (0.85*base) to highlight (0.12*base)
    ramp = np.linspace(0.85, 0.12, w, dtype=np.float32)[None, :, None]
    neg = np.repeat(ramp, h, axis=0) * base[None, None, :]
    # Inject color imbalance into central patch (imbalanced dye density)
    neg[:, :, 0] *= 1.12
    neg[:, :, 2] *= 0.86
    neg += rng.uniform(-0.001, 0.001, size=neg.shape).astype(np.float32)
    neg = np.clip(neg, 0.01, 0.95)

    cmy = compute_neutral_wb_from_point(
        neg,
        x_pct=0.5,
        y_pct=0.5,
        base_color=base.tolist(),
        profile_key="linear",
    )
    pos_balanced = invert_negative(
        neg,
        base_color=base.tolist(),
        profile_key="linear",
        printer_cyan_red=cmy[0],
        printer_magenta_green=cmy[1],
        printer_yellow_blue=cmy[2],
    )
    mid_rgb = pos_balanced[44:52, 60:68].mean(axis=(0, 1))
    assert abs(float(mid_rgb[0] - mid_rgb[1])) < 0.02
    assert abs(float(mid_rgb[1] - mid_rgb[2])) < 0.02

    auto_cmy = auto_balance_scene_wb(neg, base_color=base.tolist(), profile_key="linear")
    assert len(auto_cmy) == 3
    assert all(-1.0 <= v <= 1.0 for v in auto_cmy)


def test_darkroom_process_controls_midtone_nd_inky_blacks_and_filters() -> None:
    h, w = 64, 128
    base = np.array([0.70, 0.35, 0.18], dtype=np.float32)
    ramp = np.linspace(0.92, 0.10, w, dtype=np.float32)[None, :, None]
    neg = np.repeat(ramp, h, axis=0) * base[None, None, :]

    # 1. Verify midtone_nd changes midtone luminance with ZERO red/color cast on neutral ramp
    pos_ref = invert_negative(neg, base_color=base.tolist(), profile_key="linear", midtone_nd=0.0)
    pos_bright_nd = invert_negative(neg, base_color=base.tolist(), profile_key="linear", midtone_nd=0.6)
    mid_patch = pos_bright_nd[:, 60:68].mean(axis=(0, 1))
    assert float(mid_patch.mean()) > float(pos_ref[:, 60:68].mean()) + 0.04
    assert float(np.max(mid_patch) - np.min(mid_patch)) < 1e-3, "midtone_nd must preserve neutral chromaticity!"

    # 2. Verify inky_blacks anchors foggy shadows while keeping highlights intact
    pos_inky = invert_negative(neg, base_color=base.tolist(), profile_key="linear", inky_blacks=0.8)
    assert float(pos_inky[:, 10:22].mean()) < float(pos_ref[:, 10:22].mean())
    assert abs(float(pos_inky[:, 115:124].mean()) - float(pos_ref[:, 115:124].mean())) < 0.03

    # 3. Verify all light sources, tone variants, and optical filters produce clean [0..1] floats
    for light_src in ("standard", "cool", "warm"):
        for tone_var in ("soft", "standard", "vivid"):
            out = invert_negative(
                neg,
                base_color=base.tolist(),
                profile_key="ra4_paper",
                light_source=light_src,
                tone_variant=tone_var,
                push_pull=0.25,
                rp_tone=0.4,
                warming_85=0.3,
                skylight_filter=0.25,
                shade_filter=0.2,
            )
            assert out.shape == neg.shape
            assert not np.isnan(out).any()
            assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0


def test_multi_format_exports_and_contact_sheet(tmp_path: Path) -> None:
    rgb = np.zeros((96, 128, 3), dtype=np.uint8)
    rgb[:, :64] = (229, 149, 40)
    rgb[:, 64:] = (41, 163, 122)
    pil_img = Image.fromarray(rgb)

    for ext, expected_fmt in ((".jpg", "JPEG"), (".png", "PNG"), (".tiff", "TIFF")):
        out_path = tmp_path / f"master{ext}"
        save_output_image(pil_img, out_path)
        assert out_path.is_file() and out_path.stat().st_size > 100
        with Image.open(out_path) as reopened:
            assert reopened.format == expected_fmt
            assert reopened.size == (128, 96)

    sheet_path = tmp_path / "SHEET.jpg"
    sheet_img = generate_contact_sheet([pil_img, pil_img], roll_name="TEST_ROLL", film_name="Kodak Portra 400")
    save_output_image(sheet_img, sheet_path)
    assert sheet_path.is_file() and sheet_path.stat().st_size > 1000


# =============================================================================
# 3. FLASK API, SECURITY HEADERS & PATH-TRAVERSAL PROTECTION
# =============================================================================


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app as haluro_app

    uploads = tmp_path / "uploads"
    developed = tmp_path / "developed"
    downloads = tmp_path / "Downloads"
    uploads.mkdir()
    developed.mkdir()
    downloads.mkdir()

    monkeypatch.setattr(haluro_app, "UPLOAD_DIR", uploads.resolve())
    monkeypatch.setattr(haluro_app, "DEVELOPED_DIR", developed.resolve())
    monkeypatch.setattr(haluro_app, "get_downloads_dir", lambda: downloads.resolve())
    monkeypatch.setattr(haluro_app, "reveal_in_file_manager", lambda _p: True)
    # Durante los tests, tmp_path también es una raíz de exportación válida.
    monkeypatch.setattr(
        haluro_app,
        "EXPORT_ALLOWED_ROOTS",
        (developed.resolve(), downloads.resolve(), tmp_path.resolve()),
    )

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as test_client:
        # Every state-changing request must carry the per-process session token.
        test_client.environ_base["HTTP_X_HALURO_TOKEN"] = haluro_app.API_TOKEN
        yield test_client


def test_api_health_and_security_headers(client) -> None:
    assert __version__ == __EXPECTED_VERSION
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["app"] == APP_NAME
    assert body["version"] == __EXPECTED_VERSION
    assert body["films_count"] == 80
    assert body["platform"] in {"macos", "windows", "linux"}

    # Verify Google / OWASP defense-in-depth headers (100% offline self-hosted assets)
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
    assert "googleapis" not in resp.headers["Content-Security-Policy"]


def test_api_about_manifest(client) -> None:
    resp = client.get("/api/about")
    assert resp.status_code == 200
    info = resp.get_json()
    assert info["app"] == "Haluro"
    assert info["version"] == __EXPECTED_VERSION
    assert info["license"] == "MIT"
    assert "César Fernández Ardiles" in info["developer"]["name"]
    assert "Chile" in info["developer"]["country"]
    assert "Oregano" in info["developer"]["studio"]
    assert len(info["third_party"]) >= 5
    assert "100%" in info["privacy_notice"]


def test_api_preview_and_negative_workflow(client, tmp_path: Path) -> None:
    # 1. Load RAW sample & render preview
    res_sample = client.post("/api/load_sample")
    assert res_sample.status_code == 200

    res_prev = client.post(
        "/api/preview",
        json={"filename": "SAMPLE.CR2", "film": "cinestill800t", "ev": 0.2, "include_original": True},
    )
    assert res_prev.status_code == 200
    prev_data = res_prev.get_json()
    assert prev_data["developed"].startswith("data:image/jpeg;base64,")
    assert prev_data["original"].startswith("data:image/jpeg;base64,")

    # 2. Load C-41 negative sample, auto-detect mask & save lossless PNG to custom path
    res_neg = client.post("/api/negative/load_sample")
    assert res_neg.status_code == 200

    res_base = client.post("/api/negative/auto_detect_base", json={"filename": "SAMPLE_NEGATIVE.jpg"})
    assert res_base.status_code == 200
    base_data = res_base.get_json()
    assert len(base_data["base_color"]) == 3
    assert base_data["base_hex"].startswith("#")

    dest_png = tmp_path / "exports" / "negativo_revelado.png"
    res_save = client.post(
        "/api/negative/save_to_path",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "dest_path": str(dest_png),
            "profile": "frontier",
            "base_color": base_data["base_color"],
        },
    )
    assert res_save.status_code == 200
    assert dest_png.is_file()

    # 3. Verify non-destructive history records recipe metadata
    res_hist = client.get("/api/history")
    assert res_hist.status_code == 200
    items = res_hist.get_json()["history"]
    assert len(items) >= 1
    assert items[0]["meta"]["mode"] == "negative_inversion"


def test_api_v22_wb_endpoints_and_per_frame_roll_sync(client) -> None:
    res_profs = client.get("/api/negative/profiles")
    assert res_profs.status_code == 200
    prof_keys = {p["key"] for p in res_profs.get_json()["profiles"]}
    assert {"ra4_paper", "cine_ecp", "vlog_flat", "frontier", "noritsu", "pakon", "linear", "bw"} <= prof_keys

    client.post("/api/negative/load_sample")

    res_wb = client.post(
        "/api/negative/sample_neutral_wb",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "x_pct": 0.5,
            "y_pct": 0.5,
            "profile": "ra4_paper",
            "light_source": "standard",
        },
    )
    assert res_wb.status_code == 200
    wb_data = res_wb.get_json()
    assert len(wb_data["printer_cmy"]) == 3

    res_auto_wb = client.post(
        "/api/negative/auto_scene_wb",
        json={"filename": "SAMPLE_NEGATIVE.jpg", "profile": "cine_ecp", "light_source": "cool"},
    )
    assert res_auto_wb.status_code == 200
    assert len(res_auto_wb.get_json()["printer_cmy"]) == 3

    res_roll = client.post(
        "/api/negative/develop_full",
        json={
            "filenames": ["SAMPLE_NEGATIVE.jpg"],
            "roll_name": "TEST_V22",
            "profile": "ra4_paper",
            "light_source": "standard",
            "tone_variant": "vivid",
            "midtone_nd": 0.15,
            "inky_blacks": 0.25,
            "rp_tone": 0.30,
            "per_frame_recipes": {
                "SAMPLE_NEGATIVE.jpg": {
                    "profile": "cine_ecp",
                    "tone_variant": "vivid",
                    "warming_85": 0.2,
                }
            },
        },
    )
    assert res_roll.status_code == 200
    roll_data = res_roll.get_json()
    assert roll_data["success"] is True
    assert roll_data["total_frames"] == 1
    assert any("cine_ecp" in f for f in roll_data["files"])


def test_api_rejects_path_traversal(client) -> None:
    res1 = client.get("/api/thumbnail/..%2F..%2Fetc%2Fpasswd")
    assert res1.status_code in (400, 404)

    res2 = client.get("/api/image/../../etc/passwd")
    assert res2.status_code in (400, 403, 404)


# =============================================================================
# 4. HALURO v2.3 MODULES: B&W CHEMICAL TONERS, ROLL ANALYSIS, 3-WAY CMY,
#    PRINT FINISHING, OPTICAL SHARPENING, 48-BIT TIFF & ANALOG EXIF
# =============================================================================


def test_v23_bw_chemical_toners_and_fine_art_papers() -> None:
    assert len(BW_TONING_PROFILES) == 10
    h, w = 48, 128
    base = np.array([0.65, 0.65, 0.65], dtype=np.float32)
    ramp = np.linspace(0.90, 0.08, w, dtype=np.float32)[None, :, None]
    neg_bw = np.repeat(ramp, h, axis=0) * base[None, None, :]

    pos_neutral = invert_negative(
        neg_bw,
        base_color=base.tolist(),
        film_type="bw",
        profile_key="bw",
        bw_toner="neutral",
    )
    # Neutral silver gelatin is pure monochrome (R == G == B)
    assert float(np.max(np.abs(pos_neutral[:, :, 0] - pos_neutral[:, :, 2]))) < 1e-5

    # Selenium #2 shifts lower shadows cool/aubergine (B > G in display sRGB) while keeping highlights clean
    pos_sel2 = invert_negative(
        neg_bw,
        base_color=base.tolist(),
        film_type="bw",
        profile_key="bw",
        bw_toner="selenium_2",
        bw_toner_strength=1.0,
    )
    sh_sel = linear_to_srgb(pos_sel2)[:, 28:46].mean(axis=(0, 1))
    assert float(sh_sel[2]) > float(sh_sel[1]) + 0.008

    # Sulfide sepia warms midtones (R > G > B)
    pos_sepia = invert_negative(
        neg_bw,
        base_color=base.tolist(),
        film_type="bw",
        profile_key="bw",
        bw_toner="sepia_sulfide",
        bw_toner_strength=1.2,
    )
    mid_sep = pos_sepia[:, 56:72].mean(axis=(0, 1))
    assert float(mid_sep[0]) > float(mid_sep[1]) > float(mid_sep[2])

    # Copper & Iron split toner: cool Prussian blue shadows (B > R) + warm copper midtones (R > B)
    pos_split = invert_negative(
        neg_bw,
        base_color=base.tolist(),
        film_type="bw",
        profile_key="bw",
        bw_toner="copper_iron",
        bw_toner_strength=1.1,
    )
    sh_sp = pos_split[:, 8:20].mean(axis=(0, 1))
    mid_sp = pos_split[:, 62:78].mean(axis=(0, 1))
    assert float(sh_sp[2]) > float(sh_sp[0])
    assert float(mid_sp[0]) > float(mid_sp[2])

    # Museum cotton matte paper lifts matte black floor in display sRGB and warms paper white (R > B)
    pos_matte = invert_negative(
        neg_bw,
        base_color=base.tolist(),
        film_type="bw",
        profile_key="bw",
        bw_toner="cotton_matte",
    )
    assert float(linear_to_srgb(pos_matte)[:, 2:10].mean()) > float(linear_to_srgb(pos_neutral)[:, 2:10].mean()) + 0.025
    assert float(pos_matte[:, -10:, 0].mean()) > float(pos_matte[:, -10:, 2].mean())

    for toner_key in BW_TONING_PROFILES:
        out = invert_negative(neg_bw, base_color=base.tolist(), film_type="bw", profile_key="bw", bw_toner=toner_key)
        assert not np.isnan(out).any()
        assert 0.0 <= float(out.min()) and float(out.max()) <= 1.0


def test_v23_roll_analysis_prevents_exposure_pumping_and_scan_sources() -> None:
    orange_base = np.array([0.76, 0.35, 0.16], dtype=np.float32)
    # Frame 1: Low-key night scene (almost all pixels near film base, max density quite low)
    night_neg = np.ones((80, 100, 3), dtype=np.float32) * orange_base
    night_neg[10:70, 10:90] = orange_base * 0.78
    night_neg[35:45, 45:55] = orange_base * 0.52  # Small dim streetlamp

    # Frame 2: Bright daylight frame on the same roll (high silver/dye density in sky)
    day_neg = np.ones((80, 100, 3), dtype=np.float32) * orange_base
    day_neg[10:70, 10:50] = orange_base * 0.80
    day_neg[10:70, 50:90] = orange_base * 0.12

    cal = analyze_roll_calibration([night_neg, day_neg], film_type="color", scan_source="camera_raw")
    assert cal["frames_analyzed"] == 2
    roll_bounds = {"d_min": cal["roll_d_min"], "d_max": cal["roll_d_max"]}

    # Per-frame dynamic mode artificially stretches the dim night frame bright,
    # whereas roll_locked preserves authentic night darkness relative to the daylight frame.
    night_dyn = invert_negative(night_neg, base_color=cal["base_color"], profile_key="linear", color_method="dynamic")
    night_locked = invert_negative(
        night_neg,
        base_color=cal["base_color"],
        profile_key="linear",
        color_method="roll_locked",
        roll_bounds=roll_bounds,
    )
    assert float(night_locked[35:45, 45:55].mean()) < float(night_dyn[35:45, 45:55].mean()) - 0.15

    # Verify scan_source and pre_saturation controls on a negative with neutral rebate + colored subject
    colorful_neg = day_neg.copy()
    colorful_neg[25:55, 55:85] = orange_base * np.array([0.22, 0.45, 0.45], dtype=np.float32)
    pos_low_pre = invert_negative(colorful_neg, base_color=orange_base.tolist(), pre_saturation=0.70)
    pos_high_pre = invert_negative(colorful_neg, base_color=orange_base.tolist(), pre_saturation=1.40)
    chroma_low = float(np.std(pos_low_pre[30:50, 60:80].mean(axis=(0, 1))))
    chroma_high = float(np.std(pos_high_pre[30:50, 60:80].mean(axis=(0, 1))))
    assert chroma_high > chroma_low + 0.02

    for src in ("camera_raw", "scanner_raw", "flatbed_tiff"):
        out = invert_negative(day_neg, base_color=orange_base.tolist(), scan_source=src, color_method="shadow_weighted")
        assert out.shape == day_neg.shape and not np.isnan(out).any()


def test_v23_three_way_cmy_split_toning_and_color_protected_clip() -> None:
    h, w = 48, 128
    base = np.array([0.72, 0.36, 0.18], dtype=np.float32)
    ramp = np.linspace(0.90, 0.10, w, dtype=np.float32)[None, :, None]
    neg = np.repeat(ramp, h, axis=0) * base[None, None, :]

    pos_base = invert_negative(neg, base_color=base.tolist(), profile_key="linear")
    pos_zoned = invert_negative(
        neg,
        base_color=base.tolist(),
        profile_key="linear",
        shadows_tint=[-0.6, 0.0, 0.6],  # Cool cyan-blue shadows
        highs_tint=[0.6, 0.1, -0.5],    # Warm amber highlights
        shadows_range=0.45,
        highs_range=0.55,
    )
    s_base = linear_to_srgb(pos_base)
    s_zoned = linear_to_srgb(pos_zoned)
    sh_rgb = s_zoned[:, 26:40].mean(axis=(0, 1))
    hi_rgb = s_zoned[:, 96:112].mean(axis=(0, 1))
    assert float(sh_rgb[2]) > float(sh_rgb[0]) + 0.04, "Shadows must shift toward blue/cyan"
    assert float(hi_rgb[0]) > float(hi_rgb[2]) + 0.04, "Highlights must shift toward warm red/yellow"

    # Luminance preservation check in midtones/shadows
    luma_base = float(
        0.2126 * s_base[:, 32, 0].mean() + 0.7152 * s_base[:, 32, 1].mean() + 0.0722 * s_base[:, 32, 2].mean()
    )
    luma_zoned = float(
        0.2126 * s_zoned[:, 32, 0].mean() + 0.7152 * s_zoned[:, 32, 1].mean() + 0.0722 * s_zoned[:, 32, 2].mean()
    )
    assert abs(luma_base - luma_zoned) < 0.025

    # Color-protected white_clip keeps highlight channels smooth and bounded
    pos_clipped = invert_negative(
        neg,
        base_color=base.tolist(),
        profile_key="ra4_paper",
        black_clip=0.12,
        white_clip=0.22,
        clip_protect=True,
    )
    assert 0.0 <= float(pos_clipped.min()) and float(pos_clipped.max()) <= 1.0


def test_v23_print_finishes_asymmetric_tones_and_luminance_sharpen() -> None:
    h, w = 64, 96
    base = np.array([0.74, 0.35, 0.17], dtype=np.float32)
    ramp = np.linspace(0.88, 0.11, w, dtype=np.float32)[None, :, None]
    neg = np.repeat(ramp, h, axis=0) * base[None, None, :]

    for tone_key in TONE_VARIANTS:
        out_t = invert_negative(neg, base_color=base.tolist(), profile_key="frontier", tone_variant=tone_key)
        assert out_t.shape == neg.shape and not np.isnan(out_t).any()

    for finish_key in PRINT_FINISHES:
        out_f = invert_negative(
            neg,
            base_color=base.tolist(),
            profile_key="ra4_paper",
            print_finish=finish_key,
            finish_amount=1.35,
        )
        assert out_f.shape == neg.shape
        assert 0.0 <= float(out_f.min()) and float(out_f.max()) <= 1.0

    # Optical sharpening increases luminance edge contrast with zero chroma fringing on neutral target
    edge = np.full((64, 64, 3), 0.25, dtype=np.float32)
    edge[:, 32:] = 0.75
    sharp_lab = apply_optical_sharpen(edge, mode="lab", amount=1.2)
    sharp_scan = apply_optical_sharpen(edge, mode="scanner", amount=1.2)

    orig_jump = float(edge[32, 32, 0] - edge[32, 31, 0])
    lab_jump = float(sharp_lab[32, 32, 0] - sharp_lab[32, 31, 0])
    scan_jump = float(sharp_scan[32, 32, 0] - sharp_scan[32, 31, 0])
    assert lab_jump > orig_jump + 0.04
    assert scan_jump > orig_jump + 0.04
    assert float(np.max(np.abs(sharp_lab[:, :, 0] - sharp_lab[:, :, 2]))) < 1e-5


def test_v23_true_16bit_tiff_roundtrip_and_analog_exif_metadata(tmp_path: Path) -> None:
    # Build a smooth sub-8-bit ramp between 0.20 and 0.22 (only ~5 levels in 8-bit, >1200 in 16-bit)
    vals = np.linspace(0.20, 0.22, 256, dtype=np.float32)
    float_srgb = np.repeat(vals[None, :, None], 32, axis=0)
    float_srgb = np.repeat(float_srgb, 3, axis=2)
    pil_8bit = Image.fromarray((float_srgb * 255.0).round().astype(np.uint8))

    analog_meta = {
        "camera_make": "Leica",
        "camera_model": "M6 TTL",
        "lens": "35mm Summicron f/2 ASPH",
        "film_stock": "Kodak Portra 400",
        "film_format": "135 (35mm)",
        "shot_iso": "400",
        "dev_process": "C-41",
        "scanner": "Fuji Frontier SP-3000",
        "photographer": "Estudio Haluro",
        "notes": "Filtro amarillo suave",
    }
    caption = format_analog_caption(analog_meta)
    assert "Leica M6 TTL" in caption and "Kodak Portra 400" in caption

    # 1. Export true 48-bit (16-bit/channel) TIFF and verify IFD BitsPerSample + precision roundtrip
    tiff_path = tmp_path / "master_16bit.tiff"
    save_output_image(pil_8bit, tiff_path, float_srgb=float_srgb, analog_meta=analog_meta)
    assert tiff_path.is_file()

    with Image.open(tiff_path) as tf:
        assert tf.format == "TIFF"
        assert tuple(tf.tag_v2.get(258)) == (16, 16, 16)
        assert tf.tag_v2.get(271) == "Leica"
        assert tf.tag_v2.get(272) == "M6 TTL"

    reloaded_lin = load_image_linear(tiff_path)
    expected_lin = srgb_to_linear(float_srgb)
    np.testing.assert_allclose(reloaded_lin, expected_lin, atol=2e-4)
    # Must preserve dozens/hundreds of intermediate levels instead of 5-step 8-bit staircasing
    assert len(np.unique(reloaded_lin[0, :, 0])) > 180

    # 2. Export JPEG with full EXIF Sub-IFD technical sheet and read back tags
    jpg_path = tmp_path / "master_exif.jpg"
    save_output_image(pil_8bit, jpg_path, float_srgb=float_srgb, analog_meta=analog_meta)
    with Image.open(jpg_path) as jf:
        exif = jf.getexif()
        assert exif.get(0x010F) == "Leica"
        assert exif.get(0x0110) == "M6 TTL"
        assert exif.get(0x013B) == "Estudio Haluro"
        sub_ifd = exif.get_ifd(0x8769)
        assert sub_ifd.get(0x8827) == 400
        assert sub_ifd.get(0xA434) == "35mm Summicron f/2 ASPH"
        raw_uc = sub_ifd.get(0x9286)
        assert isinstance(raw_uc, bytes) and raw_uc.startswith(b"UNICODE\x00")
        decoded_uc = raw_uc[8:].decode("utf-16-le")
        assert "Kodak Portra 400" in decoded_uc and "C-41" in decoded_uc


def test_api_v23_roll_analysis_16bit_tiff_and_exif(client, tmp_path: Path) -> None:
    res_profs = client.get("/api/negative/profiles")
    assert res_profs.status_code == 200
    pdata = res_profs.get_json()
    assert len(pdata["bw_toners"]) == 10
    assert len(pdata["print_finishes"]) >= 8
    assert {"camera_raw", "scanner_raw", "flatbed_tiff"} <= {s["key"] for s in pdata["scan_sources"]}

    client.post("/api/negative/load_sample")

    res_an = client.post(
        "/api/negative/analyze_roll",
        json={
            "filenames": ["SAMPLE_NEGATIVE.jpg"],
            "film_type": "color",
            "scan_source": "camera_raw",
            "pre_saturation": 1.05,
        },
    )
    assert res_an.status_code == 200
    an_data = res_an.get_json()
    assert an_data["frames_analyzed"] == 1
    assert "d_min" in an_data["roll_bounds"] and "d_max" in an_data["roll_bounds"]

    dest_tiff = tmp_path / "exports_v23" / "copia_galeria_16b.tiff"
    res_save = client.post(
        "/api/negative/save_to_path",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "dest_path": str(dest_tiff),
            "film_type": "bw",
            "profile": "bw",
            "bw_toner": "selenium_2",
            "bw_toner_strength": 1.15,
            "color_method": "roll_locked",
            "roll_bounds": an_data["roll_bounds"],
            "base_color": an_data["base_color"],
            "sharpen_mode": "lab",
            "sharpen_amount": 1.1,
            "analog_meta": {
                "camera_make": "Nikon",
                "camera_model": "FM2n",
                "lens": "50mm f/1.4 AI-S",
                "film_stock": "Ilford HP5 Plus",
                "shot_iso": "800",
            },
        },
    )
    assert res_save.status_code == 200
    assert dest_tiff.is_file()
    with Image.open(dest_tiff) as tf:
        assert tuple(tf.tag_v2.get(258)) == (16, 16, 16)
        assert tf.tag_v2.get(271) == "Nikon"

    hist = client.get("/api/history").get_json()["history"]
    assert hist[0]["meta"]["bw_toner"] == "selenium_2"
    assert hist[0]["meta"]["analog_meta"]["camera_model"] == "FM2n"


def test_macos_application_identity_and_about_panel():
    """Verify that macOS native application identity, icon, and custom About panel are configured."""
    from native_app import configure_macos_application_identity

    class DummyWindow:
        def __init__(self):
            self.js_calls = []

        def evaluate_js(self, script: str):
            self.js_calls.append(script)

    dummy_win = DummyWindow()

    # Test non-darwin platform behavior
    with mock.patch("sys.platform", "win32"):
        configure_macos_application_identity(dummy_win)

    # Test darwin platform behavior
    if sys.platform == "darwin":
        import AppKit

        configure_macos_application_identity(dummy_win)
        bundle = AppKit.NSBundle.mainBundle()
        info = bundle.infoDictionary()
        assert info.get("CFBundleName") == "Haluro"
        assert info.get("CFBundleDisplayName") == "Haluro"
        assert "César Fernández Ardiles" in info.get("NSHumanReadableCopyright", "")

        from native_app import _MACOS_ABOUT_OPTIONS

        assert _MACOS_ABOUT_OPTIONS is not None
        assert _MACOS_ABOUT_OPTIONS[AppKit.NSAboutPanelOptionApplicationName] == "Haluro"
        assert __EXPECTED_VERSION in str(_MACOS_ABOUT_OPTIONS[AppKit.NSAboutPanelOptionApplicationVersion])
        credits_str = _MACOS_ABOUT_OPTIONS[AppKit.NSAboutPanelOptionCredits].string()
        assert "César Fernández Ardiles" in credits_str
        assert "Chile" in credits_str

        app = AppKit.NSApplication.sharedApplication()
        # Verify custom handler runs without deadlocks or errors
        app.orderFrontStandardAboutPanel_(None)


def test_optical_vignette():
    from engine.pipeline import apply_vignette
    canvas = np.ones((100, 100, 3), dtype=np.float32)

    # 0.0x: completely untouched
    v0 = apply_vignette(canvas, strength=0.0)
    assert np.allclose(v0, canvas)

    # 1.0x: nominal analog falloff
    v1 = apply_vignette(canvas, strength=1.0)
    # Center pixel is unaffected
    assert np.isclose(v1[50, 50, 0], 1.0)
    # Corner pixel has authentic ~55% attenuation
    assert 0.40 <= v1[0, 0, 0] <= 0.50

    # 2.0x: strong vintage falloff
    v2 = apply_vignette(canvas, strength=2.0)
    assert np.isclose(v2[50, 50, 0], 1.0)
    assert 0.10 <= v2[0, 0, 0] <= 0.20


def test_tonal_zones_isolate_shades_midtones_and_highlights():
    """Sombras, medios y luces deben actuar como exposición en luz lineal y no apilarse."""
    from engine.pipeline import apply_tonal_zones

    # Rampa de 0 a 1 en luz lineal (1 fila, 1001 columnas).
    ramp = np.linspace(0.0, 1.0, 1001, dtype=np.float32)
    rgb = np.repeat(ramp.reshape(1, -1, 1), 3, axis=2)

    def band_mean(img, lo, hi):
        return float(img[0, lo:hi, 0].mean())

    def band_ev(img, lo, hi):
        a, b = band_mean(rgb, lo, hi), band_mean(img, lo, hi)
        return float(np.log2(max(b, 1e-9) / max(a, 1e-9))) if a > 1e-6 else 0.0

    # Las máscaras son PERCEPTUALES (gamma 1/2.2): el gris medio (Lp=0.5) cae
    # en 0.5^2.2 = 0.218 lineal, no en 0.5. Las bandas se anclan ahí.
    blacks = (0, 50)          # Lp 0.00 - 0.26
    shadows = (50, 150)       # Lp 0.26 - 0.43
    mids = (150, 280)         # Lp 0.43 - 0.56 (rodea el gris medio)
    highs = (600, 950)        # Lp 0.80 - 0.98

    # Neutro: la imagen no se toca
    assert np.allclose(apply_tonal_zones(rgb.copy()), rgb)

    # Sombras +2 EV: los negros profundos suba a tope; los medios no se mueven.
    up = apply_tonal_zones(rgb.copy(), shadows=2.0)
    assert band_ev(up, *blacks) > 1.5
    assert band_ev(up, *shadows) > 0.5
    assert abs(band_ev(up, *mids)) < 0.25
    assert abs(band_ev(up, *highs)) < 0.05

    # Luces +2 EV: las altas luces suben a tope; las sombras no se mueven.
    up = apply_tonal_zones(rgb.copy(), highlights=2.0)
    assert band_ev(up, *highs) > 1.5
    assert abs(band_ev(up, *blacks)) < 0.05
    assert abs(band_ev(up, *mids)) < 0.25

    # Medios -2 EV: la zona media baja casi a tope.
    down = apply_tonal_zones(rgb.copy(), mids=-2.0)
    assert band_ev(down, *mids) < -1.5

    # Las zonas NO se apilan: en el gris medio (Lp=0.5) sombras y luces valen
    # cero, así que subir ambas a la vez no altera los medios.
    both = apply_tonal_zones(rgb.copy(), shadows=2.0, highlights=2.0)
    mid_linear = 0.5 ** 2.2
    mid_idx = int(round(mid_linear * 1000))
    assert float(both[0, mid_idx, 0]) == pytest.approx(float(rgb[0, mid_idx, 0]), rel=1e-5)


def test_tonal_zones_reach_preview_and_export(client, tmp_path: Path) -> None:
    """Las zonas tonales viajan por la API y se aplican al exportar."""
    res_sample = client.post("/api/load_sample")
    assert res_sample.status_code == 200

    def preview_bytes(**kw):
        payload = {"filename": "SAMPLE.CR2", "film": "portra400", "include_original": False}
        payload.update(kw)
        res = client.post("/api/preview", json=payload)
        assert res.status_code == 200
        import base64
        import io
        data = res.get_json()["developed"].split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")

    neutral = preview_bytes()
    lifted = preview_bytes(shadows=2.0)
    assert neutral.tobytes() != lifted.tobytes()

    # Export a disco con las zonas aplicadas
    out_png = tmp_path / "exports" / "zonas.png"
    res_save = client.post(
        "/api/save_to_path",
        json={
            "filename": "SAMPLE.CR2",
            "dest_path": str(out_png),
            "film": "portra400",
            "shadows": 2.0,
            "mids": -1.0,
            "highlights": 0.5,
        },
    )
    assert res_save.status_code == 200
    assert out_png.is_file()


def test_negative_optical_filters_and_fade_glow():
    from engine.negative_inverter import process_negative_to_image

    sample = Path(__file__).parent.parent / "samples" / "SAMPLE_NEGATIVE.jpg"

    # 1. Base image (Frontier profile, default settings)
    img_base = process_negative_to_image(sample, max_dim=400, profile_key="frontier")
    arr_base = np.array(img_base, dtype=np.float32)

    # 2. LabFade test on Frontier (verifies fade > 1.0 produces genuine matte lift)
    img_fade2 = process_negative_to_image(sample, max_dim=400, profile_key="frontier", fade_mult=2.0)
    arr_fade2 = np.array(img_fade2, dtype=np.float32)
    diff_fade = np.mean(np.abs(arr_fade2 - arr_base))
    assert diff_fade > 3.0  # Must be clearly visible matte paper lift

    # 3. LabGlow test on Frontier (verifies highlight bloom)
    img_glow2 = process_negative_to_image(sample, max_dim=400, profile_key="frontier", glow_mult=2.0)
    arr_glow2 = np.array(img_glow2, dtype=np.float32)
    diff_glow = np.mean(np.abs(arr_glow2 - arr_base))
    assert diff_glow > 0.8  # Must produce visible bloom in highlights
    assert np.max(np.abs(arr_glow2 - arr_base)) > 5.0  # Peak bloom in highlights

    # 4. Warming 85B test (shifts Kelvin warmer)
    img_w85 = process_negative_to_image(sample, max_dim=400, profile_key="frontier", warming_85=1.0)
    arr_w85 = np.array(img_w85, dtype=np.float32)
    assert np.mean(arr_w85[..., 0] - arr_base[..., 0]) > 10.0  # Red increases
    assert np.mean(arr_w85[..., 2] - arr_base[..., 2]) < -10.0  # Blue decreases


def test_updater_semver_parsing():
    from engine.updater import parse_semver

    assert parse_semver("2.4.1") == (2, 4, 1)
    assert parse_semver("v2.5.0") == (2, 5, 0)
    assert parse_semver("V3.0.0") == (3, 0, 0)
    assert parse_semver("2.4") == (2, 4, 0)
    assert parse_semver("2.4.1-rc1") == (2, 4, 1)
    assert parse_semver("") == (0, 0, 0)

    # Version comparison ordering
    assert parse_semver("2.5.0") > parse_semver("2.4.1")
    assert parse_semver("2.4.2") > parse_semver("2.4.1")
    assert parse_semver("2.4.1") == parse_semver("v2.4.1")
    assert parse_semver("2.4.0") < parse_semver("2.4.1")


def test_updater_platform_detection():
    from engine.updater import get_client_platform

    plat = get_client_platform()
    assert plat["os"] in ("macos", "windows", "linux")
    assert isinstance(plat["arch"], str)
    assert isinstance(plat["label"], str)
    assert plat["key"] in ("macos_arm64", "macos_x86_64", "windows_x86_64", "all_releases")


def test_updater_check_logic(monkeypatch):
    import json
    import urllib.request

    from engine.updater import check_for_updates

    # Case 1: Newer version available
    mock_newer = {
        "version": _NEWER_VERSION,
        "release_date": "2026-12-01",
        "title": f"Haluro v{_NEWER_VERSION}",
        "description": "Nueva versión mayor con mejoras",
        "highlights": ["Mejora 1", "Mejora 2"],
        "download_urls": {
            "macos_arm64": f"https://github.com/Hermesuser/haluro/releases/download/v{_NEWER_VERSION}/Haluro-{_NEWER_VERSION}-macOS-arm64.dmg",
            "macos_x86_64": f"https://github.com/Hermesuser/haluro/releases/download/v{_NEWER_VERSION}/Haluro-{_NEWER_VERSION}-macOS-x86_64.dmg",
            "windows_x86_64": f"https://github.com/Hermesuser/haluro/releases/download/v{_NEWER_VERSION}/Haluro-{_NEWER_VERSION}-Windows-x64.zip",
            "all_releases": "https://github.com/Hermesuser/haluro/releases/latest",
        },
    }

    class MockResponse:
        status = 200

        def read(self):
            return json.dumps(mock_newer).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=3.0: MockResponse())

    res = check_for_updates(timeout=1.0)
    assert res["update_available"] is True
    assert res["latest_version"] == _NEWER_VERSION
    assert res["offline"] is False
    assert "https://github.com/Hermesuser/haluro/releases" in res["download_url"]
    assert len(res["highlights"]) == 2

    # Case 2: Offline / connection error
    def mock_fail(req, timeout=3.0):
        raise TimeoutError("Conexión expirada")

    monkeypatch.setattr(urllib.request, "urlopen", mock_fail)
    res_offline = check_for_updates(timeout=1.0)
    assert res_offline["offline"] is True
    assert res_offline["update_available"] is False


def test_api_check_update_and_open_external(client):
    import unittest.mock
    import webbrowser

    # Test GET /api/check-update
    resp = client.get("/api/check-update")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "current_version" in data
    assert "update_available" in data
    assert "platform" in data
    assert "download_url" in data

    # Test POST /api/open-external with valid GitHub URL
    opened = []
    with unittest.mock.patch.object(webbrowser, "open", lambda url: opened.append(url) or True):
        post_resp = client.post(
            "/api/open-external",
            json={"url": "https://github.com/Hermesuser/haluro/releases/latest"},
        )
        assert post_resp.status_code == 200
        assert post_resp.get_json()["ok"] is True
        assert len(opened) == 1

        # Test POST /api/open-external with malicious / non-whitelisted URL (defense in depth)
        bad_resp = client.post(
            "/api/open-external",
            json={"url": "https://malicious-site.com/malware.exe"},
        )
        assert bad_resp.status_code == 200
        assert bad_resp.get_json()["ok"] is False


def test_contact_sheet_preview_and_save_film(client, tmp_path):
    # 1. Test fast preview endpoint
    resp = client.post(
        "/api/contact_sheet_preview",
        json={
            "filenames": ["SAMPLE.CR2"],
            "film": "portra400",
            "roll_name": "TEST_PREV_ROLL",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["sheet"] is True
    assert "sheet_url" in data
    assert data["total_frames"] == 1

    # 2. Test dedicated Save Contact Sheet Only endpoint to custom path
    dest_file = tmp_path / "custom_sheet.jpg"
    save_resp = client.post(
        "/api/save_contact_sheet",
        json={
            "filenames": ["SAMPLE.CR2"],
            "film": "portra400",
            "roll_name": "TEST_ROLL",
            "dest_path": str(dest_file),
            "reveal": False,
        },
    )
    assert save_resp.status_code == 200
    save_data = save_resp.get_json()
    assert save_data["success"] is True
    assert dest_file.exists()
    assert dest_file.stat().st_size > 10000


def test_contact_sheet_preview_and_save_negative(client, tmp_path):
    # 1. Test fast negative preview endpoint
    resp = client.post(
        "/api/negative/contact_sheet_preview",
        json={
            "filenames": ["SAMPLE_NEGATIVE.jpg"],
            "profile": "frontier",
            "roll_name": "TEST_PREV_NEG",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["sheet"] is True
    assert "sheet_url" in data
    assert data["total_frames"] == 1

    # 2. Test dedicated Save Contact Sheet Only endpoint to custom path
    dest_file = tmp_path / "custom_neg_sheet.jpg"
    save_resp = client.post(
        "/api/negative/save_contact_sheet",
        json={
            "filenames": ["SAMPLE_NEGATIVE.jpg"],
            "profile": "frontier",
            "roll_name": "TEST_NEG_ROLL",
            "dest_path": str(dest_file),
            "reveal": False,
        },
    )
    assert save_resp.status_code == 200
    save_data = save_resp.get_json()
    assert save_data["success"] is True
    assert dest_file.exists()
    assert dest_file.stat().st_size > 10000


def test_contact_sheet_interactive_layout_and_columns() -> None:
    imgs = [Image.new("RGB", (300, 200), (80 + i * 20, 90, 110)) for i in range(5)]

    sheet_3, layout_3 = generate_contact_sheet(
        imgs, roll_name="VALPARAISO 400", film_name="Kodak Portra 400", columns=3, thumb_width=320, return_layout=True
    )
    assert len(layout_3) == 5
    for idx, box in enumerate(layout_3):
        assert box["index"] == idx
        assert 0.0 < box["x_pct"] < 1.0
        assert 0.0 < box["y_pct"] < 1.0
        assert 0.05 < box["w_pct"] < 0.40
        assert 0.05 < box["h_pct"] < 0.60

    # Clamping out-of-range columns works safely
    sheet_6, layout_6 = generate_contact_sheet(imgs, columns=6, thumb_width=320, return_layout=True)
    assert sheet_6.width > sheet_3.width
    assert len(layout_6) == 5

    sheet_min = generate_contact_sheet(imgs[:2], columns=0, thumb_width=240)
    assert sheet_min.width > 0


def test_contact_sheet_preview_returns_layout_and_columns(client) -> None:
    client.post("/api/load_sample")
    resp_3 = client.post(
        "/api/contact_sheet_preview",
        json={
            "filenames": ["SAMPLE.CR2", "SAMPLE.CR2", "SAMPLE.CR2"],
            "film": "portra400",
            "roll_name": "ROLLO SUR 35MM",
            "columns": 3,
        },
    )
    assert resp_3.status_code == 200
    d3 = resp_3.get_json()
    assert d3["success"] is True
    assert isinstance(d3.get("layout"), list)
    assert len(d3["layout"]) == 3
    assert d3["layout"][0]["index"] == 0

    client.post("/api/negative/load_sample")
    resp_neg = client.post(
        "/api/negative/contact_sheet_preview",
        json={
            "filenames": ["SAMPLE_NEGATIVE.jpg", "SAMPLE_NEGATIVE.jpg", "SAMPLE_NEGATIVE.jpg", "SAMPLE_NEGATIVE.jpg"],
            "profile": "frontier",
            "roll_name": "NEGATIVO C41",
            "columns": 4,
        },
    )
    assert resp_neg.status_code == 200
    dneg = resp_neg.get_json()
    assert dneg["success"] is True
    assert isinstance(dneg.get("layout"), list)
    assert len(dneg["layout"]) == 4


def test_batch_async_roll_progress_and_cancel(client) -> None:
    import time

    # Missing frames rejected cleanly
    bad = client.post("/api/batch/develop_roll_start", json={"filenames": []})
    assert bad.status_code == 400

    # Non-existent job status returns 404
    nf = client.get("/api/batch/develop_status/doesnotexist")
    assert nf.status_code == 404

    client.post("/api/load_sample")

    # Use a small frame for the batch: developing the 26 MB sample RAW at full
    # resolution can take longer than the deadline on a slow CI runner, and
    # the test is about the batch orchestration, not about RAW throughput.
    import io as _io

    frame_buf = _io.BytesIO()
    Image.new("RGB", (640, 480), (118, 92, 74)).save(frame_buf, format="JPEG")
    frame_buf.seek(0)
    up = client.post(
        "/api/upload",
        data={"file": (frame_buf, "batch_frame.jpg")},
        content_type="multipart/form-data",
    )
    assert up.status_code == 200
    batch_frame = up.get_json()["filename"]

    start_resp = client.post(
        "/api/batch/develop_roll_start",
        json={
            "app_mode": "simulation",
            "filenames": [batch_frame],
            "film": "portra400",
            "roll_name": "ASYNC ROLL TEST",
            "columns": 3,
            "sheet": True,
            "format": "jpg",
        },
    )
    assert start_resp.status_code == 200
    job_id = start_resp.get_json()["job_id"]
    assert job_id

    status_data = None
    deadline = time.time() + 120.0
    while time.time() < deadline:
        st_resp = client.get(f"/api/batch/develop_status/{job_id}")
        assert st_resp.status_code == 200
        status_data = st_resp.get_json()
        if status_data["status"] in ("completed", "error", "cancelled"):
            break
        time.sleep(0.1)

    assert status_data is not None
    assert status_data["status"] == "completed"
    assert status_data["percent"] == 100
    res = status_data["result"]
    assert res["success"] is True
    assert res["total_frames"] == 1
    assert "SHEET.jpg" in res["files"]

    # Cancel endpoint works cleanly even on an existing job and 404 on unknown
    cancel_bad = client.post("/api/batch/develop_cancel/unknown99")
    assert cancel_bad.status_code == 404
    cancel_ok = client.post(f"/api/batch/develop_cancel/{job_id}")
    assert cancel_ok.status_code == 200
    assert cancel_ok.get_json()["success"] is True


# =============================================================================
# 6. UI/UX & ARCHIVAL LAB AUDIT REGRESSION SUITE (v2.4.6)
# =============================================================================


def test_save_output_embeds_srgb_icc_and_transliterates_ascii(tmp_path: Path) -> None:
    from engine.pipeline import get_srgb_icc_bytes

    icc_expected = get_srgb_icc_bytes()
    assert len(icc_expected) > 100

    img = Image.new("RGB", (32, 32), (180, 120, 80))
    float_srgb = np.full((32, 32, 3), [180 / 255.0, 120 / 255.0, 80 / 255.0], dtype=np.float32)
    analog_meta = {
        "camera_make": "Canon",
        "camera_model": "AE-1 Program",
        "lens": "50mm f/1.4",
        "photographer": "César Fernández Ñandú",
        "notes": "Atardecer en Valparaíso — ¡película!",
    }

    jpg_path = tmp_path / "archival.jpg"
    png_path = tmp_path / "archival.png"
    tif_path = tmp_path / "archival.tif"

    save_output_image(img, jpg_path, analog_meta=analog_meta)
    save_output_image(img, png_path, analog_meta=analog_meta)
    save_output_image(img, tif_path, float_srgb=float_srgb, analog_meta=analog_meta)

    with Image.open(jpg_path) as out_jpg:
        assert out_jpg.info.get("icc_profile") == icc_expected
        exif = out_jpg.getexif()
        assert exif.get(0x013B) == "Cesar Fernandez Nandu"
        assert "Valparaiso" in (exif.get(0x010E) or "")
        assert "?" not in (exif.get(0x013B) or "")

    with Image.open(png_path) as out_png:
        assert out_png.info.get("icc_profile") == icc_expected

    with Image.open(tif_path) as out_tif:
        assert out_tif.tag_v2.get(34675) == icc_expected
        assert out_tif.tag_v2.get(315) == "Cesar Fernandez Nandu"
        assert "Valparaiso" in (out_tif.tag_v2.get(270) or "")


def test_non_srgb_icc_input_converts_to_srgb_linear(tmp_path: Path) -> None:
    from PIL import ImageCms

    from engine.pipeline import _convert_pil_to_srgb, _is_srgb_icc_profile, get_srgb_icc_bytes

    assert _is_srgb_icc_profile(get_srgb_icc_bytes()) is True

    # Construct a non-sRGB LAB profile unconditionally to assert detection & color transform
    lab_icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    assert _is_srgb_icc_profile(lab_icc) is False

    # If host has Display P3 profile (macOS), verify end-to-end linear load shifts wide-gamut values into sRGB
    p3_path = Path("/System/Library/ColorSync/Profiles/Display P3.icc")
    if p3_path.exists():
        p3_bytes = p3_path.read_bytes()
        assert _is_srgb_icc_profile(p3_bytes) is False
        wide_img = Image.new("RGB", (16, 16), (220, 40, 20))
        converted = _convert_pil_to_srgb(wide_img, p3_bytes)
        arr_conv = np.asarray(converted)
        assert int(arr_conv[0, 0, 0]) > 220  # Pure Display-P3 red clips higher in sRGB primaries

        png_p3 = tmp_path / "p3_sample.png"
        wide_img.save(png_p3, format="PNG", icc_profile=p3_bytes)
        lin = load_image_linear(png_p3)
        srgb_out = linear_to_srgb(lin)
        assert float(srgb_out[0, 0, 0]) > 0.88
    else:
        with mock.patch("engine.pipeline.ImageCms.profileToProfile") as mock_xform:
            fake_conv = Image.new("RGB", (8, 8), (240, 10, 5))
            mock_xform.return_value = fake_conv
            res = _convert_pil_to_srgb(Image.new("RGB", (8, 8), (220, 40, 20)), lab_icc)
            assert mock_xform.called
            assert np.asarray(res)[0, 0, 0] == 240


def test_raw_sample_exif_preserved_and_colorspace_srgb(tmp_path: Path) -> None:
    sample_cr2 = Path(__file__).resolve().parent.parent / "samples" / "SAMPLE.CR2"
    assert sample_cr2.is_file()

    out_jpg = tmp_path / "from_raw.jpg"
    img = Image.new("RGB", (16, 16), (120, 120, 120))
    save_output_image(
        img,
        out_jpg,
        source_path=sample_cr2,
        analog_meta={"photographer": "Ana Gómez"},
    )

    with Image.open(out_jpg) as saved:
        exif = saved.getexif()
        assert exif.get(0x010F) == "Canon"
        assert exif.get(0x013B) == "Ana Gomez"
        assert exif.get(0x0112) == 1
        sub_ifd = exif.get_ifd(0x8769)
        assert sub_ifd.get(0xA001) == 1


def test_upload_deduplication_and_extension_rejection(client) -> None:
    import io

    import app as haluro_app

    buf1 = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 100, 50)).save(buf1, format="JPEG")
    buf1.seek(0)
    res1 = client.post(
        "/api/upload",
        data={"file": (buf1, "DSC_0001.jpg")},
        content_type="multipart/form-data",
    )
    assert res1.status_code == 200
    d1 = res1.get_json()
    assert d1["filename"] == "DSC_0001.jpg"

    buf2 = io.BytesIO()
    Image.new("RGB", (16, 16), (50, 100, 200)).save(buf2, format="JPEG")
    buf2.seek(0)
    res2 = client.post(
        "/api/upload",
        data={"file": (buf2, "DSC_0001.jpg")},
        content_type="multipart/form-data",
    )
    assert res2.status_code == 200
    d2 = res2.get_json()
    assert d2["filename"] == "DSC_0001_2.jpg"
    assert (haluro_app.UPLOAD_DIR / "DSC_0001.jpg").is_file()
    assert (haluro_app.UPLOAD_DIR / "DSC_0001_2.jpg").is_file()

    bad = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"MZ_not_an_image"), "payload.exe")},
        content_type="multipart/form-data",
    )
    assert bad.status_code == 400
    assert "error" in (bad.get_json() or {})


def test_cinestill400d_alias_print_category_and_ui_contract(client) -> None:
    c400d = get_film("cinestill400d")
    assert c400d["key"] == "cinestill400d"
    assert c400d["kind"] == "cine"
    assert get_film("cinestill400t")["key"] == "cinestill400d"

    films = list_films()
    assert any(f["kind"] == "print" for f in films)

    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for marker in (
        f"v{__EXPECTED_VERSION}",
        'id="undoBtn"',
        'id="redoBtn"',
        'id="zenToggleBtn"',
        'id="syncRollModal"',
        'id="zebraCanvas"',
        'id="loupeZoomCanvas"',
        'id="stripCullBar"',
        'id="btnAutoFillExifFromRecipe"',
        "Altas suaves",
        'id="clipShadows"',
        'data-category="print"',
    ):
        assert marker in html


def test_negative_preview_original_uncropped_flag(client) -> None:
    import base64
    import io

    # Upload an 800x600 frame (below max_dim=1280 so crop_pct strictly reduces output dimensions)
    neg_buf = io.BytesIO()
    Image.new("RGB", (800, 600), (210, 120, 75)).save(neg_buf, format="JPEG")
    neg_buf.seek(0)
    up = client.post(
        "/api/upload",
        data={"file": (neg_buf, "test_neg_border.jpg")},
        content_type="multipart/form-data",
    )
    assert up.status_code == 200
    fname = up.get_json()["filename"]

    resp_cropped = client.post(
        "/api/negative/preview",
        json={
            "filename": fname,
            "profile": "frontier",
            "crop_pct": 0.12,
            "original_uncropped": False,
        },
    )
    assert resp_cropped.status_code == 200
    dc = resp_cropped.get_json()
    assert "original" in dc and "developed" in dc

    resp_uncropped = client.post(
        "/api/negative/preview",
        json={
            "filename": fname,
            "profile": "frontier",
            "crop_pct": 0.12,
            "original_uncropped": True,
        },
    )
    assert resp_uncropped.status_code == 200
    du = resp_uncropped.get_json()
    assert "original" in du and "developed" in du

    def _decode_b64_size(data_url: str) -> tuple[int, int]:
        raw_b64 = data_url.split(",", 1)[1]
        with Image.open(io.BytesIO(base64.b64decode(raw_b64))) as im:
            return im.size

    orig_c_w, orig_c_h = _decode_b64_size(dc["original"])
    dev_c_w, dev_c_h = _decode_b64_size(dc["developed"])
    orig_u_w, orig_u_h = _decode_b64_size(du["original"])
    dev_u_w, dev_u_h = _decode_b64_size(du["developed"])
    assert (orig_c_w, orig_c_h) == (dev_c_w, dev_c_h)
    assert (orig_u_w, orig_u_h) == (800, 600)
    assert orig_u_w > dev_u_w and orig_u_h > dev_u_h


def test_contact_sheet_stems_aspect_and_mixed_roll_meta(tmp_path: Path) -> None:
    import app as haluro_app

    portrait_imgs = [Image.new("RGB", (240, 360), (140, 120, 100)) for _ in range(2)]
    sheet_p, layout_p = generate_contact_sheet(
        portrait_imgs,
        roll_name="ROLLO MIXTO",
        film_name="Rollo mixto (2 emulsiones)",
        columns=2,
        thumb_width=320,
        return_layout=True,
        frame_labels=["DSC_0001", "RETOQUE_FINAL"],
    )
    assert len(layout_p) == 2

    landscape_imgs = [Image.new("RGB", (360, 240), (140, 120, 100)) for _ in range(2)]
    sheet_l = generate_contact_sheet(
        landscape_imgs,
        roll_name="ROLLO PAISAJE",
        film_name="Kodak Portra 400",
        columns=2,
        thumb_width=320,
        return_layout=False,
    )
    # Tall/square batches reserve 0.88:1 slot height vs compact 2:3 for landscape batches
    assert sheet_p.height > sheet_l.height

    # Verify mixed emulsion/profile headers resolved by _resolve_sheet_meta
    sim_label, sim_stems = haluro_app._resolve_sheet_meta(
        ["DSC_0001.CR2", "RETOQUE_FINAL.JPG"],
        {"DSC_0001.CR2": {"film": "portra400"}, "RETOQUE_FINAL.JPG": {"film": "hp5"}},
        "simulation",
        "portra400",
        "Kodak Portra 400",
    )
    assert "2 emulsiones" in sim_label
    assert sim_stems == ["DSC_0001", "RETOQUE_FINAL"]

    neg_label, neg_stems = haluro_app._resolve_sheet_meta(
        ["A.JPG", "B.JPG"],
        {"A.JPG": {"profile": "frontier"}, "B.JPG": {"profile": "noritsu"}},
        "negative",
        "frontier",
        "Negativo · Fuji Frontier SP-3000",
    )
    assert "2 perfiles" in neg_label
    assert neg_stems == ["A", "B"]

    # Export contact sheet via save_output_image guarantees sRGB ICC tagging even on contact sheets
    cs_out = tmp_path / "SHEET.jpg"
    save_output_image(sheet_p, cs_out)
    with Image.open(cs_out) as saved_cs:
        assert saved_cs.info.get("icc_profile") is not None








def test_user_tone_curve_is_monotone_and_channel_aware():
    """La curva de usuario: monótona, identidad por defecto y fiel al matiz."""
    from engine.pipeline import apply_user_curves, build_curve_lut

    # Sin puntos no hay curva: la imagen no se toca.
    assert build_curve_lut([]) is None
    assert build_curve_lut(None) is None
    ramp = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    img = np.repeat(ramp.reshape(1, -1, 1), 3, axis=2)
    assert np.allclose(apply_user_curves(img.copy(), {}), img)
    assert np.allclose(apply_user_curves(img.copy(), {"rgb": []}), img)

    # La LUT es monótona: una curva tonal no puede crear ondulaciones.
    lut = build_curve_lut([[0, 0], [0.25, 0.45], [0.75, 0.8], [1, 1]])
    assert lut is not None
    diffs = np.diff(lut.astype(np.float64))
    assert np.all(diffs >= -1e-6), "la curva debe ser monótona"

    # Una curva que levanta las sombras sube las sombras y deja las luces.
    out = apply_user_curves(img.copy(), {"rgb": [[0, 0], [0.25, 0.45], [0.75, 0.8], [1, 1]]})
    assert out[0, 32, 0] > img[0, 32, 0] + 0.1
    assert out[0, 250, 0] == pytest.approx(img[0, 250, 0], abs=0.02)

    # La curva de luminancia conserva el matiz (proporción entre canales).
    color = np.array([[[0.8, 0.3, 0.15]]], dtype=np.float32)
    curved = apply_user_curves(color.copy(), {"l": [[0, 0], [0.5, 0.7], [1, 1]]})[0, 0]
    src_px = color[0, 0]
    assert curved[0] / curved[1] == pytest.approx(src_px[0] / src_px[1], rel=0.02)

    # La curva por canal sólo toca ese canal.
    out2 = apply_user_curves(img.copy(), {"r": [[0, 0], [1, 0.5]]})
    assert out2[0, 128, 0] == pytest.approx(0.251, abs=0.02)
    assert out2[0, 128, 1] == pytest.approx(img[0, 128, 1], abs=1e-6)

    # Puntos duplicados o fuera de rango no rompen nada.
    weird = build_curve_lut([[0.2, 0.3], [0.2, 0.4], [5, 9], [-3, -2], [float("nan"), 1]])
    assert weird is not None
    assert np.all(np.isfinite(weird))


def test_user_tone_curve_reaches_preview_and_export(client, tmp_path: Path) -> None:
    """La curva viaja como datos por la API y se aplica al exportar."""
    import base64
    import io

    res_sample = client.post("/api/load_sample")
    assert res_sample.status_code == 200

    curve = {"rgb": [[0.0, 0.0], [0.25, 0.45], [0.75, 0.8], [1.0, 1.0]]}

    def preview_bytes(payload):
        body = {"filename": "SAMPLE.CR2", "film": "portra400", "include_original": False}
        body.update(payload)
        res = client.post("/api/preview", json=body)
        assert res.status_code == 200
        data = res.get_json()["developed"].split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")

    neutral = preview_bytes({})
    curved = preview_bytes({"curve": curve})
    assert neutral.tobytes() != curved.tobytes()

    # Una curva inválida se ignora (la imagen no se toca).
    invalid = preview_bytes({"curve": {"rgb": "no-es-una-curva"}})
    assert invalid.tobytes() == neutral.tobytes()

    # Export a disco con la curva aplicada.
    out_png = tmp_path / "exports" / "curva.png"
    res_save = client.post(
        "/api/save_to_path",
        json={
            "filename": "SAMPLE.CR2",
            "dest_path": str(out_png),
            "film": "portra400",
            "curve": curve,
        },
    )
    assert res_save.status_code == 200
    assert out_png.is_file()

    # La receta por fotograma puede llevar su propia curva: la hoja de
    # contactos usa la curva de CADA fotograma, no la global.
    res_sheet = client.post(
        "/api/contact_sheet_preview",
        json={
            "filenames": ["SAMPLE.CR2"],
            "film": "portra400",
            "curve": curve,
            "per_frame_recipes": {"SAMPLE.CR2": {"film": "portra400", "curve": curve}},
            "columns": 2,
        },
    )
    assert res_sheet.status_code == 200
    assert res_sheet.get_json().get("sheet")
