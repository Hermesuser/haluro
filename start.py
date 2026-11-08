#!/usr/bin/env python3
"""Web launcher for Haluro — Laboratorio Analógico Digital."""

import socket
import webbrowser
import threading
import time


def find_free_port(start_port=5050):
    port = start_port
    while port < 6000:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port


def open_browser(url):
    time.sleep(1.0)
    print(f"  Abriendo mesa de luz de Haluro en: {url}")
    webbrowser.open(url)


if __name__ == "__main__":
    port = find_free_port(5050)
    url = f"http://127.0.0.1:{port}"

    print("\n" + "=" * 62)
    print("  HALURO — LABORATORIO ANALÓGICO DIGITAL (v2.0)")
    print("=" * 62)
    print(f"  • Servidor activo en: {url}")
    print("  • Emulación: 72 películas químicas + LUTs 3D")
    print("  • Negativos: Inversión óptica C-41 / B&N + Minilab")
    print("  • Flujo 100% no destructivo · Pulsa Ctrl+C para salir")
    print("=" * 62 + "\n")

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    from app import app

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
