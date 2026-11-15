"""Tests para las mejoras inspiradas en Disparafilm (P1 en adelante)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from engine.negative_inverter import (
    FILM_SUBSTRATES,
    analyze_roll_calibration,
    apply_dust_spot_healing,
    apply_flat_field_correction,
    auto_balance_scene_wb,
    auto_detect_film_base,
    compute_flat_field_gain_map,
    invert_negative,
    list_film_substrates,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        haluro_app,
        "EXPORT_ALLOWED_ROOTS",
        (developed.resolve(), downloads.resolve(), tmp_path.resolve()),
    )

    haluro_app.app.config["TESTING"] = True
    with haluro_app.app.test_client() as test_client:
        test_client.environ_base["HTTP_X_HALURO_TOKEN"] = haluro_app.API_TOKEN
        yield test_client


def _synthetic_negative(seed: int = 42, base_rgb=(0.75, 0.36, 0.16)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h, w = 96, 128
    img = np.zeros((h, w, 3), dtype=np.float32)
    grad_x = np.linspace(0.25, 0.92, w, dtype=np.float32)[None, :]
    grad_y = np.linspace(0.30, 0.85, h, dtype=np.float32)[:, None]
    for c, base_val in enumerate(base_rgb):
        img[..., c] = base_val * (0.35 + 0.65 * grad_x * (0.7 + 0.3 * grad_y))
    # Clear film border around edges
    img[:6, :, :] = base_rgb
    img[-6:, :, :] = base_rgb
    img[:, :6, :] = base_rgb
    img[:, -6:, :] = base_rgb
    noise = rng.normal(0.0, 0.005, size=img.shape).astype(np.float32)
    return np.clip(img + noise, 0.02, 0.99)


def test_p1_film_substrates_registry_and_backward_compat() -> None:
    keys = {item["key"] for item in list_film_substrates()}
    assert {"c41_orange", "clear_base", "phoenix", "warm_base", "creative_switch"} <= keys
    assert len(keys) == len(FILM_SUBSTRATES)

    neg = _synthetic_negative()
    out_default = invert_negative(neg)
    out_explicit = invert_negative(neg, film_substrate="c41_orange")
    assert np.allclose(out_default, out_explicit, atol=1e-6)


def test_p1_all_substrates_valid_bounds_and_distinct_behavior() -> None:
    clear_neg = _synthetic_negative(seed=7, base_rgb=(0.955, 0.92, 0.93))
    detected_c41 = auto_detect_film_base(clear_neg, film_substrate="c41_orange")
    detected_clear = auto_detect_film_base(clear_neg, film_substrate="clear_base")
    # Clear base allows high transmittance up to 0.97 instead of discarding >= 0.94 pixels
    assert detected_clear[0] >= detected_c41[0]

    outputs = {}
    for sub_key in FILM_SUBSTRATES:
        out = invert_negative(clear_neg, film_substrate=sub_key)
        assert out.shape == clear_neg.shape
        assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0
        assert not np.isnan(out).any()
        outputs[sub_key] = out

    # Phoenix and creative_switch must differ measurably from standard orange-mask inversion
    assert not np.allclose(outputs["phoenix"], outputs["c41_orange"], atol=1e-3)
    assert not np.allclose(outputs["creative_switch"], outputs["c41_orange"], atol=1e-3)


def test_p1_creative_substrate_preserves_intentional_cast_in_auto_wb() -> None:
    # Negative with strong warm/amber shift (like redscale / switched couplers)
    neg = _synthetic_negative(seed=11, base_rgb=(0.82, 0.50, 0.25))
    neg[..., 2] *= 0.65
    cmy_c41 = auto_balance_scene_wb(neg, film_substrate="c41_orange")
    cmy_creative = auto_balance_scene_wb(neg, film_substrate="creative_switch")
    # Creative mode avoids aggressive neutralization compared to C-41 standard
    assert sum(abs(v) for v in cmy_creative) <= sum(abs(v) for v in cmy_c41) + 1e-4

    cal = analyze_roll_calibration([neg, neg * 0.95], film_substrate="phoenix")
    assert len(cal["base_color"]) == 3


def test_p1_flask_api_substrates_and_fallback(client) -> None:
    prof_res = client.get("/api/negative/profiles")
    assert prof_res.status_code == 200
    payload = prof_res.get_json()
    assert "film_substrates" in payload
    assert any(s["key"] == "phoenix" for s in payload["film_substrates"])

    # Preview accepts explicit substrate and falls back gracefully on invalid value
    res_phoenix = client.post(
        "/api/negative/preview",
        json={"filename": "SAMPLE_NEGATIVE.jpg", "film_substrate": "phoenix", "include_original": False},
    )
    assert res_phoenix.status_code == 200
    assert res_phoenix.get_json()["developed"].startswith("data:image/jpeg;base64,")

    res_invalid = client.post(
        "/api/negative/preview",
        json={"filename": "SAMPLE_NEGATIVE.jpg", "film_substrate": "unknown_sub", "include_original": False},
    )
    assert res_invalid.status_code == 200


def test_p2_keep_sprockets_preserves_dimensions_and_ignores_border_artifacts(client) -> None:
    # Build negative with extreme pure-black holder edges & bright white sprocket holes (outer 8%)
    neg = _synthetic_negative(seed=21, base_rgb=(0.75, 0.36, 0.16))
    neg[:8, :, :] = 0.01  # Black film holder / rebate
    neg[-8:, :, :] = 0.01
    neg[2:5, 10::16, :] = 0.99  # Bright unmasked LED sprocket holes

    # Standard crop_pct=0.08 shrinks dimensions; keep_sprockets=True preserves exact frame dimensions!
    cropped = invert_negative(neg, border_buffer=0.02, crop_pct=0.08, keep_sprockets=False)
    sprockets = invert_negative(neg, border_buffer=0.02, crop_pct=0.08, keep_sprockets=True)
    assert cropped.shape[0] < neg.shape[0] and cropped.shape[1] < neg.shape[1]
    assert sprockets.shape == neg.shape

    # Inner photo region remains balanced (not crushed dark by 0.99 sprockets or blown out by 0.01 holder)
    center_mean = float(np.mean(sprockets[16:-16, 16:-16]))
    assert 0.15 < center_mean < 0.85

    # Flask endpoint accepts keep_sprockets cleanly without trimming original or developed preview
    res_full = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "crop_pct": 0.10,
            "keep_sprockets": False,
            "include_original": False,
        },
    )
    res_sp = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "crop_pct": 0.10,
            "keep_sprockets": True,
            "include_original": False,
        },
    )
    assert res_full.status_code == 200 and res_sp.status_code == 200
    assert res_sp.get_json()["width"] > res_full.get_json()["width"]


def test_p3_flat_field_vignetting_correction_and_upload_api(client) -> None:
    h, w = 96, 128
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = (h - 1) * 0.5, (w - 1) * 0.5
    r2 = ((yy - cy) / cy) ** 2 + ((xx - cx) / cx) ** 2
    falloff = np.clip(1.0 - 0.25 * r2, 0.45, 1.0)[..., None]

    # Blank LED panel with center 0.85 and 25%+ corner light falloff
    blank_led = np.full((h, w, 3), 0.85, dtype=np.float32) * falloff
    gain_grid, metrics = compute_flat_field_gain_map(blank_led, grid_size=64)
    assert gain_grid.shape == (64, 64, 3)
    assert metrics["corner_falloff_pct"] > 10.0

    corrected = apply_flat_field_correction(blank_led, gain_grid, strength=1.0)
    orig_corner_ratio = float(np.mean(blank_led[:8, :8]) / np.mean(blank_led[40:56, 56:72]))
    corr_corner_ratio = float(np.mean(corrected[:8, :8]) / np.mean(corrected[40:56, 56:72]))
    assert abs(1.0 - corr_corner_ratio) < abs(1.0 - orig_corner_ratio)

    # Full inversion accepts flat_field_gain cleanly
    out_ff = invert_negative(
        _synthetic_negative() * falloff,
        flat_field_gain=gain_grid,
        flat_field_strength=1.0,
    )
    assert float(out_ff.min()) >= 0.0 and float(out_ff.max()) <= 1.0

    # Flask upload + preview + safe handling of traversal flat_field_file
    arr_u8 = np.rint(np.clip(blank_led, 0.0, 1.0) * 255.0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr_u8).save(buf, format="JPEG")
    buf.seek(0)
    up_res = client.post(
        "/api/negative/flat_field/upload",
        data={"file": (buf, "led_blank.jpg")},
        content_type="multipart/form-data",
    )
    assert up_res.status_code == 200
    up_json = up_res.get_json()
    assert up_json["flat_field_file"].startswith("__haluro_flatfield_")
    assert up_json["corner_falloff_pct"] > 5.0

    prev_res = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "flat_field_file": up_json["flat_field_file"],
            "flat_field_strength": 1.0,
            "include_original": False,
        },
    )
    assert prev_res.status_code == 200

    # Traversal string must be ignored safely rather than exposing files
    trav_res = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "flat_field_file": "../../etc/passwd",
            "include_original": False,
        },
    )
    assert trav_res.status_code == 200


def test_p4_bw_split_grade_and_preflash(client) -> None:
    neg = _synthetic_negative(seed=33, base_rgb=(0.72, 0.72, 0.72))

    # Backward compatibility: zeroed split grade + preflash == unchanged B&W output
    bw_base = invert_negative(neg, film_type="bw", profile_key="bw")
    bw_zero = invert_negative(
        neg,
        film_type="bw",
        profile_key="bw",
        bw_grade00=0.0,
        bw_grade5=0.0,
        bw_preflash=0.0,
    )
    assert np.allclose(bw_base, bw_zero, atol=1e-6)

    # Positive Grade 00 pulls bright highlight tones gently down without muddying deep shadows
    bw_g00 = invert_negative(neg, film_type="bw", profile_key="bw", bw_grade00=0.8)
    # Positive Grade 5 deepens shadows firmly
    bw_g5 = invert_negative(neg, film_type="bw", profile_key="bw", bw_grade5=0.8)
    # Pre-flash softens bright peak intensity
    bw_pf = invert_negative(neg, film_type="bw", profile_key="bw", bw_preflash=0.9)

    assert float(np.percentile(bw_g00, 95)) < float(np.percentile(bw_base, 95))
    assert float(np.percentile(bw_pf, 98)) < float(np.percentile(bw_base, 98))
    assert float(np.percentile(bw_g5, 10)) <= float(np.percentile(bw_base, 10))

    # Color mode must ignore B&W split-grade/preflash cleanly
    col_a = invert_negative(neg, film_type="color", profile_key="frontier")
    col_b = invert_negative(
        neg, film_type="color", profile_key="frontier", bw_grade00=0.9, bw_grade5=0.9, bw_preflash=0.9
    )
    assert np.allclose(col_a, col_b, atol=1e-6)

    res = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "film_type": "bw",
            "profile": "bw",
            "bw_grade00": 0.45,
            "bw_grade5": 0.65,
            "bw_preflash": 0.35,
            "include_original": False,
        },
    )
    assert res.status_code == 200


def test_p5_negative_tone_curve(client) -> None:
    neg = _synthetic_negative(seed=41, base_rgb=(0.82, 0.48, 0.25))

    col_base = invert_negative(neg, film_type="color", profile_key="frontier")
    col_empty = invert_negative(neg, film_type="color", profile_key="frontier", curve=None)
    assert np.allclose(col_base, col_empty, atol=1e-6)

    lift_curve = {"rgb": [[0.25, 0.34], [0.75, 0.84]], "r": [[0.5, 0.62]]}
    col_curved = invert_negative(neg, film_type="color", profile_key="frontier", curve=lift_curve)
    assert float(col_curved.mean()) > float(col_base.mean()) + 0.02
    assert float((col_curved[..., 0] - col_base[..., 0]).mean()) > float((col_curved[..., 2] - col_base[..., 2]).mean())

    # Works in B&W darkroom branch too
    bw_base = invert_negative(neg, film_type="bw", profile_key="bw")
    bw_curved = invert_negative(neg, film_type="bw", profile_key="bw", curve={"l": [[0.5, 0.66]]})
    assert float(bw_curved.mean()) > float(bw_base.mean()) + 0.02

    res = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "curve": lift_curve,
            "include_original": False,
        },
    )
    assert res.status_code == 200
    assert res.get_json()["developed"].startswith("data:image/jpeg;base64,")


def test_p5_test_strip_endpoint(client) -> None:
    import base64

    import app as haluro_app

    # Vertical gradients invariant across X so each vertical band shares identical scene content
    grad_y = np.linspace(0.15, 0.85, 120, dtype=np.float32)[:, None, None]
    grey_u8 = np.rint(np.broadcast_to(grad_y, (120, 250, 3)) * 255.0).astype(np.uint8)
    grey_path = haluro_app.UPLOAD_DIR / "vertical_grad_grey.png"
    Image.fromarray(grey_u8).save(grey_path)

    base_rgb = np.array([0.82, 0.48, 0.25], dtype=np.float32)
    neg_lin = base_rgb * (0.18 + 0.72 * grad_y)
    neg_u8 = np.rint(np.clip(np.broadcast_to(neg_lin, (120, 250, 3)) ** (1.0 / 2.2), 0.0, 1.0) * 255.0).astype(np.uint8)
    neg_path = haluro_app.UPLOAD_DIR / "vertical_grad_neg.png"
    Image.fromarray(neg_u8).save(neg_path)

    for mode, step_ev, fname in (
        ("simulation", 0.3333, grey_path.name),
        ("negative", 0.5, neg_path.name),
    ):
        payload = {
            "mode": mode,
            "step_ev": step_ev,
            "filename": fname,
        }
        if mode == "simulation":
            payload.update({"vignette": 0.0, "grain": 0.0})
        else:
            payload["base_color"] = base_rgb.tolist()
        res = client.post("/api/test_strip", json=payload)
        assert res.status_code == 200
        data = res.get_json()
        assert data["strip"].startswith("data:image/jpeg;base64,")
        assert len(data["steps"]) == 5
        deltas = [s["delta_ev"] for s in data["steps"]]
        assert deltas == sorted(deltas)
        assert abs(deltas[2]) < 1e-3

        raw_b64 = data["strip"].split(",", 1)[1]
        img = Image.open(io.BytesIO(base64.b64decode(raw_b64)))
        arr = np.asarray(img, dtype=np.float32)
        w = arr.shape[1]
        col_means = [
            float(arr[:, int(i * w / 5) + 4 : int((i + 1) * w / 5) - 4].mean())
            for i in range(5)
        ]
        assert col_means == sorted(col_means)
        assert col_means[4] > col_means[0] + 10.0


def test_p6_contemporary_stocks_and_dev_process(client) -> None:
    from engine.films import get_film, list_films
    from engine.pipeline import DEV_PROCESSES, develop_frame

    films = list_films()
    keys = {f["key"] for f in films}
    expected_new = {
        "phoenix200",
        "harman_switch",
        "santacolor100",
        "lomochrome92",
        "metropolis400",
        "lomo_purple",
        "doublex5222",
        "fomapan400",
    }
    assert expected_new.issubset(keys)
    assert len([f for f in films if not f.get("is_user_lut")]) == 80

    # /api/films exposes the chemical development process catalog
    f_res = client.get("/api/films")
    assert f_res.status_code == 200
    f_body = f_res.get_json()
    assert len([f for f in f_body["films"] if not f.get("is_user_lut")]) == 80
    assert {p["key"] for p in f_body["dev_processes"]} == set(DEV_PROCESSES.keys())

    # Synthetic gradient verifies Push +2 EV brightens/increases contrast while Stand Rodinal tames peaks
    grad = np.broadcast_to(np.linspace(0.05, 0.95, 96, dtype=np.float32)[:, None, None], (96, 96, 3)).copy()
    _, std_f = develop_frame(
        grad.copy(), film_key="fomapan400", grain_mult=0.0, dev_process="standard", return_float=True
    )
    _, std_explicit = develop_frame(
        grad.copy(), film_key="fomapan400", grain_mult=0.0, return_float=True
    )
    assert np.allclose(std_f, std_explicit, atol=1e-6)

    _, push2_f = develop_frame(
        grad.copy(), film_key="fomapan400", grain_mult=0.0, dev_process="push_2", return_float=True
    )
    _, stand_f = develop_frame(
        grad.copy(), film_key="fomapan400", grain_mult=0.0, dev_process="stand_rodinal", return_float=True
    )
    assert float(push2_f[48:, ...].mean()) > float(std_f[48:, ...].mean()) + 0.03
    assert float(stand_f[-12:, ...].mean()) <= float(push2_f[-12:, ...].mean())

    # Verify /api/preview works with new film + dev_process and unknown dev_process falls back safely
    for proc in ("stand_rodinal", "push_1", "push_2", "nonexistent_proc"):
        res = client.post(
            "/api/preview",
            json={
                "filename": "SAMPLE.CR2",
                "film": "phoenix200" if proc != "push_2" else "doublex5222",
                "dev_process": proc,
                "include_original": False,
            },
        )
        assert res.status_code == 200
        assert res.get_json()["film"]["key"] in {get_film("phoenix200")["key"], get_film("doublex5222")["key"]}


def test_p7_essential_mode_and_minilab_ui(client):
    """P7: Vista Esencial/Completa y atajos de Minilab estilo Fuji Frontier presentes en HTML/CSS/JS."""
    html_res = client.get("/")
    assert html_res.status_code == 200
    html = html_res.get_data(as_text=True)

    assert 'id="uiComplexityBtn"' in html
    assert "Vista Esencial (Minilab)" in html
    assert "Balance Minilab CMY" in html
    for adv_id in (
        'id="negCaptureDrawer"',
        'id="negRollAnalysisDrawer"',
        'id="negFineToneDrawer"',
        'id="cmyZoneBar"',
        'id="negOpticalPanel"',
        'id="analogExifDetails"',
    ):
        assert adv_id in html
    assert html.count("ui-adv-only") >= 7

    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert "body.ui-essential .ui-adv-only" in css

    js = client.get("/static/js/app.js").get_data(as_text=True)
    for fn_name in ("toggleEssentialView", "nudgeExposure", "nudgeCmyChannel"):
        assert f"function {fn_name}" in js


def test_p8_dust_spot_healing_and_reciprocity_ui(client):
    """P8: Limpieza puntual de motas sin IR, endpoint negativo y calculadora EXIF/reciprocidad."""
    clean = np.full((80, 80, 3), 0.35, dtype=np.float32)
    assert np.allclose(apply_dust_spot_healing(clean, None), clean)
    assert np.allclose(apply_dust_spot_healing(clean, []), clean)

    dusty = clean.copy()
    dusty[38:42, 38:42, :] = 0.98
    healed = apply_dust_spot_healing(dusty, [{"x": 0.5, "y": 0.5, "r": 0.045}])
    assert float(healed[39:41, 39:41].mean()) < 0.45
    assert np.allclose(healed[:10, :10], clean[:10, :10], atol=1e-6)

    res = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "film_type": "bw",
            "profile": "bw",
            "dust_spots": [{"x": 0.5, "y": 0.5, "r": 0.01}],
            "include_original": False,
        },
    )
    assert res.status_code == 200
    assert res.get_json()["developed"].startswith("data:image/")

    html = client.get("/").get_data(as_text=True)
    for elem_id in (
        'id="btnDustHealTool"',
        'id="negDustRadiusSlider"',
        'id="exifChemPresetSelect"',
        'id="recipFilmSelect"',
        'id="recipMeasuredInput"',
        'id="btnInsertRecipToNotes"',
    ):
        assert elem_id in html


def test_p9_easel_borders_and_dry_down_export(client):
    """P9: Marginador de cuarto oscuro (Easel Borders) y compensación Dry-Down en exportación."""
    from engine.pipeline import apply_darkroom_print_finishing

    arr = np.full((100, 120, 3), 0.45, dtype=np.float32)
    pil_in = Image.fromarray((arr * 255).astype(np.uint8))

    out_noop_pil, out_noop_f = apply_darkroom_print_finishing(
        pil_in, float_srgb=arr, easel_border="none", dry_down_comp=0.0
    )
    assert out_noop_pil is pil_in
    assert out_noop_f is arr

    # Dry-down lifts midtones gently without border
    dd_pil, dd_f = apply_darkroom_print_finishing(pil_in, float_srgb=arr, easel_border="none", dry_down_comp=0.08)
    assert dd_pil.size == pil_in.size
    assert float(dd_f.mean()) > float(arr.mean()) + 0.01

    # Easel white_gallery adds baryta border with weighted bottom margin
    gal_pil, gal_f = apply_darkroom_print_finishing(
        pil_in, float_srgb=arr, easel_border="white_gallery", dry_down_comp=0.0
    )
    assert gal_pil.width > pil_in.width and gal_pil.height > pil_in.height
    assert float(gal_f[2, 2].mean()) > 0.92
    assert float(gal_f[gal_f.shape[0] // 2, gal_f.shape[1] // 2].mean()) == pytest.approx(0.45, abs=0.01)

    # Easel black_rebate adds dark carrier rebate
    blk_pil, blk_f = apply_darkroom_print_finishing(
        pil_in, float_srgb=arr, easel_border="black_rebate", dry_down_comp=0.0
    )
    assert blk_pil.width > pil_in.width
    assert float(blk_f[2, 2].mean()) < 0.10

    # End-to-end /api/export_single reflects border dimension delta
    res_plain = client.post(
        "/api/export_single",
        json={"filename": "SAMPLE.CR2", "film": "portra400", "easel_border": "none", "dry_down_comp": 0.0},
    )
    res_bordered = client.post(
        "/api/export_single",
        json={"filename": "SAMPLE.CR2", "film": "portra400", "easel_border": "white_gallery", "dry_down_comp": 0.08},
    )
    assert res_plain.status_code == 200 and res_bordered.status_code == 200
    d_plain = res_plain.get_json()
    d_bordered = res_bordered.get_json()
    assert d_bordered["width"] > d_plain["width"]
    assert d_bordered["height"] > d_plain["height"]

    html = client.get("/").get_data(as_text=True)
    assert 'id="easelBorderSelect"' in html
    assert 'id="dryDownSelect"' in html







