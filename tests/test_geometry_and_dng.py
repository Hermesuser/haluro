"""Tests for unified geometry (crop, straighten, flip_v, keystone) and Linear DNG / original format export."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from PIL import Image

import app as haluro_app
from app import app
from engine.negative_inverter import process_negative_to_image
from engine.pipeline import (
    apply_geometry,
    develop_frame,
    inscribed_crop_for_angle,
    normalize_crop_rect,
    resolve_export_extension,
    save_linear_dng_16bit,
    write_geometry_xmp_sidecar,
)


def _read_tiff_tag_ids(path: Path) -> dict[int, tuple[int, int]]:
    data = path.read_bytes()
    assert data[:4] == b"II\x2a\x00"
    ifd_off = struct.unpack_from("<I", data, 4)[0]
    num_entries = struct.unpack_from("<H", data, ifd_off)[0]
    tags: dict[int, tuple[int, int]] = {}
    for idx in range(num_entries):
        entry_off = ifd_off + 2 + idx * 12
        tag, typ, cnt, _val = struct.unpack_from("<HHII", data, entry_off)
        tags[tag] = (typ, cnt)
    return tags


def test_normalize_crop_rect_and_inscribed():
    assert normalize_crop_rect(None) is None
    assert normalize_crop_rect([0.0, 0.0, 1.0, 1.0]) is None
    rect = normalize_crop_rect({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.4})
    assert rect == (0.1, 0.2, 0.5, 0.4)

    ix, iy, iw, ih = inscribed_crop_for_angle(1000, 800, 6.0)
    assert 0.0 < ix < 0.2
    assert 0.0 < iy < 0.2
    assert 0.6 < iw < 1.0
    assert 0.6 < ih < 1.0


def test_apply_geometry_flip_v_straighten_keystone_and_crop():
    arr = np.zeros((100, 200, 3), dtype=np.float32)
    arr[:10, :, 0] = 1.0  # top red band

    flipped = apply_geometry(arr, flip_v=True)
    assert flipped.shape == (100, 200, 3)
    assert float(flipped[-1, 50, 0]) == 1.0
    assert float(flipped[0, 50, 0]) == 0.0

    straightened = apply_geometry(arr, straighten=4.0, auto_crop_straighten=True)
    assert straightened.shape[0] < 100 and straightened.shape[1] < 200

    persp = apply_geometry(arr, keystone_v=10.0, keystone_h=-8.0)
    assert persp.shape == (100, 200, 3)
    assert np.isfinite(persp).all()

    cropped = apply_geometry(arr, crop_rect=(0.25, 0.10, 0.50, 0.50))
    assert cropped.shape == (50, 100, 3)


def test_develop_frame_and_negative_support_new_geometry():
    img = Image.new("RGB", (240, 160), (140, 100, 80))
    sim_out = develop_frame(
        img,
        film_key="portra400",
        flip_v=True,
        straighten=3.5,
        keystone_v=5.0,
        crop_rect=(0.1, 0.1, 0.5, 0.5),
    )
    assert sim_out.size == (120, 80)

    neg_out = process_negative_to_image(
        img,
        flip_v=True,
        straighten=-2.5,
        keystone_h=4.0,
        crop_rect=(0.2, 0.2, 0.5, 0.5),
    )
    assert neg_out.size == (120, 80)


def test_resolve_export_extension_original_and_dng():
    assert resolve_export_extension("original", "photo.JPG") == ".jpg"
    assert resolve_export_extension("original", "scan.png") == ".png"
    assert resolve_export_extension("original", "master.tif") == ".tiff"
    assert resolve_export_extension("original", "roll_01.CR3") == ".dng"
    assert resolve_export_extension("original", "roll_02.NEF") == ".dng"
    assert resolve_export_extension("original", "roll_03.dng") == ".dng"
    assert resolve_export_extension("dng", "photo.jpg") == ".dng"


def test_save_linear_dng_16bit_and_xmp_sidecar(tmp_path: Path):
    srgb = np.full((64, 96, 3), 0.5, dtype=np.float32)
    dng_path = tmp_path / "test_out.dng"
    save_linear_dng_16bit(srgb, dng_path, analog_meta={"camera_make": "Nikon", "camera_model": "FM2"})
    assert dng_path.is_file()
    tags = _read_tiff_tag_ids(dng_path)
    # 50706 DNGVersion, 50707 DNGBackwardVersion, 50708 UniqueCameraModel, 50721 ColorMatrix1, 50728 AsShotNeutral
    for req_tag in (256, 257, 258, 262, 50706, 50707, 50708, 50721, 50728):
        assert req_tag in tags

    xmp_path = write_geometry_xmp_sidecar(
        dng_path,
        rotate=90,
        flip_h=False,
        flip_v=False,
        straighten=-1.5,
        crop_rect=(0.1, 0.1, 0.8, 0.8),
    )
    assert xmp_path.is_file()
    xmp_text = xmp_path.read_text(encoding="utf-8")
    assert 'crs:HasCrop="True"' in xmp_text
    assert 'crs:CropAngle="-1.500"' in xmp_text
    assert 'tiff:Orientation="6"' in xmp_text


def test_api_preview_and_dng_export():
    client = app.test_client()
    client.environ_base["HTTP_X_HALURO_TOKEN"] = haluro_app.API_TOKEN
    r1 = client.post(
        "/api/preview",
        json={
            "filename": "SAMPLE.CR2",
            "film": "portra400",
            "flip_v": True,
            "straighten": 2.0,
            "keystone_v": 4.0,
            "crop_rect": [0.1, 0.1, 0.8, 0.8],
        },
    )
    assert r1.status_code == 200
    d1 = r1.get_json()
    assert d1["width"] > 0 and d1["height"] > 0

    r2 = client.post(
        "/api/negative/preview",
        json={
            "filename": "SAMPLE_NEGATIVE.jpg",
            "flip_v": True,
            "straighten": -1.5,
            "crop_rect": [0.1, 0.1, 0.8, 0.8],
        },
    )
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert d2["width"] > 0 and d2["height"] > 0

    r3 = client.post(
        "/api/export_single",
        json={
            "filename": "SAMPLE.CR2",
            "film": "portra400",
            "format": "original",
            "write_xmp": True,
            "flip_v": True,
            "straighten": 1.5,
            "crop_rect": [0.1, 0.1, 0.8, 0.8],
        },
    )
    assert r3.status_code == 200
    d3 = r3.get_json()
    assert d3["success"] is True
    assert d3["filename"].endswith(".dng")
    out_dng = Path(d3["path"])
    assert out_dng.is_file()
    assert out_dng.with_suffix(".xmp").is_file()
    out_dng.unlink(missing_ok=True)
    out_dng.with_suffix(".xmp").unlink(missing_ok=True)
    out_dng.with_suffix(".jpg").unlink(missing_ok=True)
    out_dng.with_suffix(".meta.json").unlink(missing_ok=True)
