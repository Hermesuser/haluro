#!/usr/bin/env python3
"""Haluro — Laboratorio Analógico Digital.

Cross-platform native desktop launcher for macOS (Cocoa WebKit) and
Windows 11 (Microsoft Edge WebView2, Per-Monitor v2 High-DPI, DWM Dark Titlebar).
"""

from __future__ import annotations

import ctypes
import json
import logging
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request

# Ensure package imports resolve in both source checkouts and frozen bundles
_BOOT_DIR = (
    Path(getattr(sys, "_MEIPASS")).resolve()
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
    else Path(__file__).resolve().parent
)
if str(_BOOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOOT_DIR))

from engine import APP_NAME, __version__  # noqa: E402
from engine.platform_io import (  # noqa: E402
    apply_windows11_dark_titlebar,
    choose_save_path_dialog,
    configure_logging,
    enable_windows11_dpi_awareness,
    get_downloads_dir,
    get_platform_tag,
    is_windows,
    open_directory,
    reveal_in_file_manager,
)

logger = logging.getLogger("haluro.native")

WINDOW_TITLE = "Haluro — Laboratorio Analógico Digital"

_ACTIVE_WINDOW: object | None = None
_MACOS_ABOUT_OPTIONS: dict[object, object] | None = None


class AppApi:
    """JavaScript <-> Native OS bridge exposed as `window.pywebview.api`."""

    def __init__(self) -> None:
        self.window = None

    def get_platform_info(self) -> dict[str, object]:
        """Return native host metadata for OS-adaptive UI."""
        return {
            "app": APP_NAME,
            "version": __version__,
            "platform": get_platform_tag(),
            "native_host": True,
        }

    def save_file_dialog(self, default_name: str) -> str | None:
        """Open native macOS Save Sheet or Windows 11 Save Dialog."""
        import webview

        safe_default = Path(default_name or "revelado_haluro.jpg").name
        expected_ext = Path(safe_default).suffix.lower() or ".jpg"
        downloads_dir = str(get_downloads_dir())

        try:
            if self.window is not None:
                dialog_mode = getattr(webview, "FileDialog", None)
                save_const = dialog_mode.SAVE if dialog_mode is not None else webview.SAVE_DIALOG
                res = self.window.create_file_dialog(
                    save_const,
                    directory=downloads_dir,
                    save_filename=safe_default,
                    file_types=(
                        "JPEG 4:4:4 (*.jpg;*.jpeg)",
                        "PNG sin pérdida (*.png)",
                        "TIFF 16-bit de archivo (*.tiff;*.tif)",
                    ),
                )
                if res:
                    chosen = res[0] if isinstance(res, (list, tuple)) else str(res)
                    if chosen and not Path(chosen).suffix:
                        chosen += expected_ext
                    return chosen
                return None
        except Exception as exc:  # pragma: no cover - GUI backend fallback
            logger.warning("pywebview save dialog error, using OS fallback: %s", exc)

        return choose_save_path_dialog(safe_default)

    def open_developed_folder(self) -> str:
        """Open the internal developed archive folder in Finder or File Explorer."""
        from app import DEVELOPED_DIR

        open_directory(DEVELOPED_DIR)
        return str(DEVELOPED_DIR)

    def reveal_file(self, file_path: str) -> bool:
        """Highlight a specific exported file in macOS Finder or Windows 11 Explorer."""
        if not file_path:
            return False
        return reveal_in_file_manager(file_path)


def find_free_port(start_port: int = 5050) -> int:
    """Bind to a free localhost TCP port to prevent multi-instance collisions."""
    for port in range(start_port, start_port + 500):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(port: int, timeout: float = 8.0) -> bool:
    """Wait until the embedded Flask backend responds on `/api/health`."""
    deadline = time.monotonic() + timeout
    health_url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=0.6) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.08)
    return False


def run_backend(port: int) -> None:
    """Run local loopback HTTP engine (`127.0.0.1` only)."""
    try:
        from app import app

        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except Exception as exc:
        logger.exception("Backend server failed to start: %s", exc)
        sys.stderr.write(f"Backend thread exception: {exc}\n")


def configure_macos_application_identity(window: object | None = None) -> None:
    """Configure native Cocoa application identity, dock icon, and About panel on macOS.

    Replaces default Python / generic folder icon with Haluro's branded camera
    optics icon, version metadata, and developer attribution for César Fernández Ardiles.
    """
    if sys.platform != "darwin":
        return

    try:
        import AppKit
    except ImportError:  # pragma: no cover
        logger.debug("AppKit not available in this Python runtime; skipping Cocoa identity.")
        return

    try:
        app_instance = AppKit.NSApplication.sharedApplication()

        # 1. Provide bundle metadata so Cocoa uses Haluro instead of python3
        bundle = AppKit.NSBundle.mainBundle()
        info = bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME
            info["CFBundleDisplayName"] = APP_NAME
            info["CFBundleShortVersionString"] = __version__
            info["CFBundleVersion"] = __version__
            info["NSHumanReadableCopyright"] = "© 2026 César Fernández Ardiles. Todos los derechos reservados."

        try:
            import webview.platforms.cocoa as cocoa

            if hasattr(cocoa, "info") and isinstance(cocoa.info, dict):
                cocoa.info["CFBundleName"] = APP_NAME
                cocoa.info["CFBundleDisplayName"] = APP_NAME
        except Exception:  # pragma: no cover
            pass

        # 2. Locate and load Haluro AppIcon.icns
        icon_path = _BOOT_DIR / "assets" / "AppIcon.icns"
        if not icon_path.is_file():
            icon_path = _BOOT_DIR.parent / "assets" / "AppIcon.icns"

        icon_img = None
        if icon_path.is_file():
            icon_img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon_path))
            if icon_img:
                app_instance.setApplicationIconImage_(icon_img)

        # 3. Build native About Panel options dictionary with developer information
        credits_text = (
            "Fotógrafo y Desarrollador: César Fernández Ardiles\n"
            "Oregano · Chile\n\n"
            f"{APP_NAME} — Laboratorio Analógico Digital (v{__version__})\n"
            "Emulación de 72 emulsiones fotográficas clásicas (C-41, B&W, E-6, ECN-2 Cine),\n"
            "conversión cromática de negativos y virados químicos de cuarto oscuro.\n\n"
            "100% No destructivo · 100% Local y Privado\n"
            "Licencia MIT (Distribución libre y gratuita)\n"
            "https://github.com/cesarfernandez/haluro"
        )
        attr_credits = AppKit.NSAttributedString.alloc().initWithString_(credits_text)

        about_options = {
            AppKit.NSAboutPanelOptionApplicationName: APP_NAME,
            AppKit.NSAboutPanelOptionApplicationVersion: f"v{__version__}",
            AppKit.NSAboutPanelOptionVersion: "Laboratorio Analógico Digital",
            AppKit.NSAboutPanelOptionCredits: attr_credits,
            "Copyright": "© 2026 César Fernández Ardiles. Todos los derechos reservados.",
        }
        if icon_img:
            about_options[AppKit.NSAboutPanelOptionApplicationIcon] = icon_img

        global _ACTIVE_WINDOW, _MACOS_ABOUT_OPTIONS
        _MACOS_ABOUT_OPTIONS = about_options

        # 4. Intercept Cocoa standard About action to show custom About panel & in-app modal
        def _haluro_order_front_about_panel(self: object, sender: object) -> None:
            try:
                self.orderFrontStandardAboutPanelWithOptions_(about_options)  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover
                logger.warning("Error displaying Cocoa native About panel with options: %s", exc)

            # Trigger in-app modal in webview window as well
            if _ACTIVE_WINDOW is not None:
                try:
                    _ACTIVE_WINDOW.evaluate_js(
                        "document.getElementById('aboutModal')?.classList.add('active');"
                    )
                except Exception as exc:  # pragma: no cover
                    logger.debug("Could not trigger in-app about modal from Cocoa menu: %s", exc)

        AppKit.NSApplication.orderFrontStandardAboutPanel_ = _haluro_order_front_about_panel

        if window is not None:
            _ACTIVE_WINDOW = window

    except Exception as exc:  # pragma: no cover
        logger.warning("Error configuring macOS application identity: %s", exc)


def _show_native_fatal_error(title: str, message: str) -> None:
    """Display an OS-native alert box if the WebView runtime cannot start."""
    logger.critical("%s: %s", title, message)
    if is_windows():
        try:
            # MB_ICONERROR (0x10) | MB_OK (0x0)
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    sys.stderr.write(f"{title}: {message}\n")


def run_smoke_test() -> int:
    """Boot backend, verify `/api/health`, validate native bridge, and exit cleanly."""
    configure_logging()
    port = find_free_port(5150)
    server_thread = threading.Thread(target=run_backend, args=(port,), daemon=True)
    server_thread.start()
    if not wait_for_server(port, timeout=10.0):
        sys.stderr.write("ERROR: Backend server failed readiness check.\n")
        return 1

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3.0) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    api = AppApi()
    payload["bridge"] = api.get_platform_info()
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("status") == "ok" and payload.get("films_count", 0) >= 72 else 1


def main() -> int:
    """Launch Haluro native desktop window on macOS or Windows 11."""
    if "--smoke-test" in sys.argv:
        return run_smoke_test()

    enable_windows11_dpi_awareness()
    log_path = configure_logging()
    logger.info("Starting %s v%s (%s) — log: %s", APP_NAME, __version__, get_platform_tag(), log_path)

    try:
        import webview
    except ImportError as exc:
        _show_native_fatal_error(
            "Haluro — Componente gráfico no disponible",
            f"No se encontró el motor de ventana nativa (pywebview): {exc}",
        )
        return 1

    port = find_free_port(5050)
    url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=run_backend, args=(port,), daemon=True)
    server_thread.start()
    if not wait_for_server(port, timeout=10.0):
        _show_native_fatal_error(
            "Haluro — Error de arranque",
            "El motor óptico local no respondió a tiempo. Revisa el registro de diagnóstico.",
        )
        return 1

    configure_macos_application_identity()

    api = AppApi()
    macos_localization = (
        {
            "cocoa.menu.about": "Acerca de",
            "cocoa.menu.services": "Servicios",
            "cocoa.menu.hide": "Ocultar",
            "cocoa.menu.hideOthers": "Ocultar otros",
            "cocoa.menu.showAll": "Mostrar todo",
            "cocoa.menu.quit": "Salir de",
            "cocoa.menu.edit": "Edición",
            "cocoa.menu.copy": "Copiar",
            "cocoa.menu.cut": "Cortar",
            "cocoa.menu.paste": "Pegar",
            "cocoa.menu.selectAll": "Seleccionar todo",
            "cocoa.menu.view": "Visualización",
            "cocoa.menu.fullscreen": "Pantalla completa",
        }
        if sys.platform == "darwin"
        else None
    )

    window = webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        width=1440,
        height=900,
        min_size=(1080, 720),
        background_color="#0B0C0E",
        text_select=False,
        zoomable=True,
        js_api=api,
        localization=macos_localization,
    )
    api.window = window
    configure_macos_application_identity(window=window)

    if sys.platform == "darwin":
        def _on_macos_shown() -> None:
            try:
                import AppKit

                main_menu = AppKit.NSApplication.sharedApplication().mainMenu()
                if main_menu and main_menu.numberOfItems() > 0:
                    first_item = main_menu.itemAtIndex_(0)
                    first_item.setTitle_(APP_NAME)
                    app_sub = first_item.submenu()
                    if app_sub and app_sub.numberOfItems() > 0:
                        about_item = app_sub.itemAtIndex_(0)
                        about_item.setTitle_(f"Acerca de {APP_NAME}")
            except Exception as exc:
                logger.debug("Menu title adjustment error: %s", exc)

        window.events.shown += _on_macos_shown

    if is_windows():
        window.events.shown += lambda: apply_windows11_dark_titlebar(WINDOW_TITLE)
        try:
            webview.start(gui="edgechromium", debug=False)
        except Exception as exc:
            logger.warning("Edge WebView2 explicit init failed (%s), trying fallback GUI.", exc)
            try:
                webview.start(debug=False)
            except Exception as inner_exc:
                _show_native_fatal_error(
                    "Haluro requiere Microsoft Edge WebView2",
                    "Windows 11 incluye WebView2 de serie, pero no pudo iniciarse en este equipo.\n\n"
                    f"Detalle técnico: {inner_exc}\n"
                    "Descarga oficial: https://go.microsoft.com/fwlink/p/?LinkId=2124703",
                )
                return 1
    else:
        webview.start(debug=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
