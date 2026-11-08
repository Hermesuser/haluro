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
from pathlib import Path
import subprocess
import sys
from unittest import mock

import numpy as np
from PIL import Image
import pytest

from engine import APP_NAME, __version__
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
from engine import platform_io


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
    assert len(films) == 72
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

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as test_client:
        yield test_client


def test_api_health_and_security_headers(client) -> None:
    assert __version__ == "2.4.0"
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["app"] == APP_NAME
    assert body["version"] == "2.4.0"
    assert body["films_count"] == 72
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
    assert info["version"] == "2.4.0"
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
