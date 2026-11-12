"""Cross-platform OS integration and filesystem layout for Haluro (macOS & Windows 11).

Follows Google production engineering standards:
- Strict separation between read-only application bundle resources (`sys._MEIPASS`)
  and user-writable application state (`~/Library/Application Support/Haluro` on macOS,
  `%LOCALAPPDATA%\\Haluro` on Windows 11).
- Zero shell/script string interpolation (all native dialog arguments passed via `argv`
  or environment variables to eliminate injection vectors).
- Native Finder (`macOS`) and File Explorer (`Windows 11`) integration.
- Cross-platform vector font resolution for macOS, Windows 11, and Linux.
- Windows 11 Per-Monitor v2 High-DPI awareness and immersive Dark Mode titlebar support.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

from PIL import ImageFont

from . import APP_NAME

logger = logging.getLogger(__name__)

FontRole = Literal["sans-bold", "sans", "mono", "mono-bold"]


def is_frozen() -> bool:
    """Return True when running inside a compiled PyInstaller bundle (.app / .exe)."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def is_windows() -> bool:
    """Return True when running on Windows (Windows 10/11)."""
    return sys.platform == "win32"


def is_macos() -> bool:
    """Return True when running on macOS (Darwin)."""
    return sys.platform == "darwin"


def get_platform_tag() -> str:
    """Return normalized platform identifier ('macos', 'windows', or 'linux')."""
    if is_macos():
        return "macos"
    if is_windows():
        return "windows"
    return "linux"


def get_resource_root() -> Path:
    """Return root directory containing read-only bundled assets.

    Assets include `templates/`, `static/`, `luts/`, `samples/`, and app icons.
    Works identically in source checkouts and frozen PyInstaller executables.
    """
    if is_frozen():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent.parent


def _is_directory_writable(directory: Path) -> bool:
    """Check whether `directory` allows creating temporary files."""
    try:
        if not directory.is_dir():
            return False
        return os.access(directory, os.W_OK)
    except OSError:
        return False


def get_user_data_root() -> Path:
    """Return writable base directory for `uploads/`, `developed/`, and `logs/`.

    Resolution priority:
      1. `HALURO_DATA_DIR` environment variable (used by tests and custom deployments).
      2. OS-standard per-user application data directory when running as a frozen
         native bundle (`.app` / `.exe`) or when the source tree is read-only
         (e.g. `C:\\Program Files\\Haluro` on Windows 11 or `/Applications` on macOS).
      3. Repository root when running directly from a writable developer workspace.
    """
    env_override = os.environ.get("HALURO_DATA_DIR", "").strip()
    if env_override:
        target = Path(env_override).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    res_root = get_resource_root()
    force_os_dir = os.environ.get("HALURO_USE_SYSTEM_APPDATA", "").strip() == "1"

    if not is_frozen() and not force_os_dir and _is_directory_writable(res_root):
        return res_root

    if is_windows():
        local_appdata = os.environ.get("LOCALAPPDATA")
        base = Path(local_appdata) if local_appdata else (Path.home() / "AppData" / "Local")
        data_dir = base / APP_NAME
    elif is_macos():
        data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
        data_dir = base / APP_NAME.lower()

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir.resolve()


def get_downloads_dir() -> Path:
    """Return the user's Downloads folder across macOS and Windows 11."""
    if is_windows():
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            cand = Path(user_profile) / "Downloads"
            if cand.exists():
                return cand.resolve()
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads.resolve()


def get_logs_dir() -> Path:
    """Return writable log directory for diagnostic and crash logs."""
    if is_macos() and is_frozen():
        log_dir = Path.home() / "Library" / "Logs" / APP_NAME
    else:
        log_dir = get_user_data_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_logging(level: int = logging.INFO) -> Path:
    """Configure structured file + console logging for production diagnostics.

    Returns:
        Path to the active log file.
    """
    log_file = get_logs_dir() / "haluro.log"
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return log_file

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Rotate the log: this is a long-running desktop application and a plain
    # FileHandler would grow the file without bound.
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    return log_file


def reveal_in_file_manager(target_path: Path | str) -> bool:
    """Highlight a file or open a folder in macOS Finder or Windows 11 Explorer."""
    path_obj = Path(target_path).expanduser().resolve()
    if not path_obj.exists():
        logger.warning("Cannot reveal non-existent path: %s", path_obj)
        return False

    try:
        if is_windows():
            norm_str = os.path.normpath(str(path_obj))
            if path_obj.is_dir():
                os.startfile(norm_str)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer.exe", f"/select,{norm_str}"])
            return True

        if is_macos():
            cmd = ["open", str(path_obj)] if path_obj.is_dir() else ["open", "-R", str(path_obj)]
            subprocess.run(cmd, check=False)
            return True

        # Linux / freedesktop fallback
        folder = path_obj if path_obj.is_dir() else path_obj.parent
        subprocess.Popen(["xdg-open", str(folder)])
        return True
    except OSError as exc:
        logger.error("Failed to reveal path %s: %s", path_obj, exc)
        return False


def open_directory(folder_path: Path | str) -> bool:
    """Open a directory in macOS Finder or Windows 11 File Explorer."""
    folder = Path(folder_path).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return reveal_in_file_manager(folder)


def choose_save_path_dialog(
    default_name: str,
    default_dir: Path | None = None,
) -> str | None:
    """Open an OS-native Save File dialog when running outside `pywebview`.

    Uses `osascript` with `argv` on macOS and STA PowerShell `SaveFileDialog`
    with environment variables on Windows 11 (zero string interpolation).

    Args:
        default_name: Suggested filename including extension (e.g. `foto_portra400.jpg`).
        default_dir: Initial folder shown in the dialog (defaults to `~/Downloads`).

    Returns:
        Absolute destination path string, or `None` if cancelled by the user.
    """
    safe_name = Path(default_name or "revelado_haluro.jpg").name
    expected_ext = Path(safe_name).suffix.lower() or ".jpg"
    initial_dir = (default_dir or get_downloads_dir()).resolve()

    if is_macos():
        applescript = (
            "on run argv\n"
            "  set defName to item 1 of argv\n"
            "  set defDir to POSIX file (item 2 of argv) as alias\n"
            "  try\n"
            '    set outFile to choose file name with prompt "Guardar imagen revelada en Haluro:" '
            "default name defName default location defDir\n"
            "    return POSIX path of outFile\n"
            "  on error number -128\n"
            '    return "CANCELLED"\n'
            "  end try\n"
            "end run"
        )
        try:
            proc = subprocess.run(
                ["osascript", "-e", applescript, "--", safe_name, str(initial_dir)],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            chosen = proc.stdout.strip()
            if not chosen or chosen == "CANCELLED":
                return None
            if not Path(chosen).suffix:
                chosen += expected_ext
            return chosen
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("macOS Save dialog failed: %s", exc)
            return None

    if is_windows():
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dlg = New-Object System.Windows.Forms.SaveFileDialog; "
            "$dlg.Title = 'Guardar imagen revelada en Haluro'; "
            "$dlg.InitialDirectory = $env:HALURO_SAVE_DIR; "
            "$dlg.FileName = $env:HALURO_SAVE_NAME; "
            "$dlg.Filter = 'JPEG 4:4:4 (*.jpg;*.jpeg)|*.jpg;*.jpeg"
            "|PNG sin pérdida (*.png)|*.png"
            "|TIFF de archivo (*.tiff;*.tif)|*.tiff;*.tif"
            "|Todos los archivos (*.*)|*.*'; "
            "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "  Write-Output $dlg.FileName "
            "} else { Write-Output 'CANCELLED' }"
        )
        env = os.environ.copy()
        env["HALURO_SAVE_NAME"] = safe_name
        env["HALURO_SAVE_DIR"] = str(initial_dir)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-STA",
                    "-Command",
                    ps_script,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=180,
                creationflags=creation_flags,
                check=False,
            )
            chosen = proc.stdout.strip()
            if not chosen or chosen == "CANCELLED":
                return None
            if not Path(chosen).suffix:
                chosen += expected_ext
            return chosen
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("Windows Save dialog failed: %s", exc)
            return None

    return None


_FONT_CANDIDATES: dict[FontRole, tuple[str, ...]] = {
    "sans-bold": (
        # macOS
        "Helvetica-Bold",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        # Windows 11
        "segoeuib.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "arialbd.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "sans": (
        "Helvetica",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "segoeui.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "mono-bold": (
        "Courier-Bold",
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
        "consolab.ttf",
        "C:/Windows/Fonts/consolab.ttf",
        "courbd.ttf",
        "C:/Windows/Fonts/courbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ),
    "mono": (
        "Courier",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "consola.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "cour.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ),
}


def load_ui_font(
    role: FontRole = "mono",
    size: int = 16,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a crisp TrueType font across macOS, Windows 11, and Linux."""
    for candidate in _FONT_CANDIDATES.get(role, ()):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def enable_windows11_dpi_awareness() -> None:
    """Enable Per-Monitor v2 High-DPI scaling on Windows 11 before window creation."""
    if not is_windows():
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # type: ignore[attr-defined]
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def apply_windows11_dark_titlebar(window_title: str) -> None:
    """Apply Windows 11 immersive dark mode (`DWMWA_USE_IMMERSIVE_DARK_MODE`) to window chrome."""
    if not is_windows():
        return
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, window_title)  # type: ignore[attr-defined]
        if not hwnd:
            return
        dwm_use_dark = ctypes.c_int(1)
        # Attribute 20 = DWMWA_USE_IMMERSIVE_DARK_MODE on Windows 11 (build 22000+)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            hwnd,
            20,
            ctypes.byref(dwm_use_dark),
            ctypes.sizeof(dwm_use_dark),
        )
    except (AttributeError, OSError) as exc:
        logger.debug("Could not apply Windows 11 DWM dark titlebar: %s", exc)


def get_runtime_diagnostics() -> dict[str, object]:
    """Return structured system diagnostics for `/api/health`."""
    return {
        "os": get_platform_tag(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "frozen": is_frozen(),
        "resource_root": str(get_resource_root()),
        "user_data_root": str(get_user_data_root()),
    }
