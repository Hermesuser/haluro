# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller specification for Haluro v2.4.4.

Targets:
  - Windows 11 x64 / ARM64 -> `dist/Haluro/Haluro.exe` (Edge WebView2, Win32 PE metadata, High-DPI)
  - macOS Apple Silicon / Intel -> `dist/Haluro.app` (Cocoa WebKit, Retina, studio.haluro.lab)
"""

from pathlib import Path
import platform
import sys
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

SPEC_ROOT = Path(SPECPATH).resolve()
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# Bundle read-only optical assets into `sys._MEIPASS`
added_datas = [
    (str(SPEC_ROOT / "templates"), "templates"),
    (str(SPEC_ROOT / "static"), "static"),
    (str(SPEC_ROOT / "luts"), "luts"),
    (str(SPEC_ROOT / "samples"), "samples"),
    (str(SPEC_ROOT / "assets"), "assets"),
]
added_datas += collect_data_files("webview")

added_binaries = []
added_binaries += collect_dynamic_libs("rawpy")
added_binaries += collect_dynamic_libs("webview")

hidden_imports = [
    "app",
    "engine",
    "engine.films",
    "engine.lut",
    "engine.pipeline",
    "engine.negative_inverter",
    "engine.contact_sheet",
    "engine.platform_io",
    "scipy.ndimage",
    "PIL._tkinter_finder",
]
hidden_imports += collect_submodules("webview")

if IS_WINDOWS:
    hidden_imports += [
        "clr",
        "clr_loader",
        "pythonnet",
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
    ]
elif IS_MACOS:
    hidden_imports += [
        "Foundation",
        "AppKit",
        "WebKit",
        "objc",
        "webview.platforms.cocoa",
    ]

a = Analysis(
    [str(SPEC_ROOT / "native_app.py")],
    pathex=[str(SPEC_ROOT)],
    binaries=added_binaries,
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "notebook", "pytest"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe_kwargs = {
    "exclude_binaries": True,
    "name": "Haluro",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "console": False,
    "disable_windowed_traceback": False,
}

if IS_WINDOWS:
    exe_kwargs["icon"] = str(SPEC_ROOT / "assets" / "haluro.ico")
    version_file = SPEC_ROOT / "packaging" / "windows" / "version_info.txt"
    if version_file.is_file():
        exe_kwargs["version"] = str(version_file)
elif IS_MACOS:
    exe_kwargs["icon"] = str(SPEC_ROOT / "assets" / "AppIcon.icns")
    exe_kwargs["argv_emulation"] = False

exe = EXE(pyz, a.scripts, [], **exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Haluro",
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name="Haluro.app",
        icon=str(SPEC_ROOT / "assets" / "AppIcon.icns"),
        bundle_identifier="studio.haluro.lab",
        info_plist={
            "CFBundleName": "Haluro",
            "CFBundleDisplayName": "Haluro",
            "CFBundleVersion": "2.4.4",
            "CFBundleShortVersionString": "2.4.4",
            "LSMinimumSystemVersion": "12.0" if platform.machine() == "x86_64" else "14.0",
            "NSHighResolutionCapable": True,
            "NSSupportsAutomaticGraphicsSwitching": True,
            "NSHumanReadableCopyright": "© 2026 César Fernández Ardiles. Todos los derechos reservados.",
        },
    )
