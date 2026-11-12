#!/usr/bin/env python3
"""Verify that the version number is consistent across the whole repository.

`engine/__init__.py` is the single source of truth. This guard exists because
a hardcoded copy in the Windows packaging scripts drifted out of sync: the
v2.4.6 release published Windows artefacts named 2.4.5 while `version.json`
pointed users at a 2.4.6 download that did not exist.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_version() -> str:
    source = (ROOT / "engine" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if not match:
        raise SystemExit("No se pudo leer __version__ de engine/__init__.py")
    return match.group(1)


def main() -> int:
    version = read_version()
    print(f"Versión canónica (engine/__init__.py): {version}")
    problems: list[str] = []

    # pyproject.toml
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if not match or match.group(1) != version:
        problems.append(f"pyproject.toml declara {match.group(1) if match else '?'}")

    # version.json
    manifest = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        problems.append(f"version.json declara {manifest.get('version')}")
    for key, url in (manifest.get("download_urls") or {}).items():
        if "releases/download" in url and f"/v{version}/" not in url:
            problems.append(f"version.json download_urls.{key} no apunta a v{version}")

    # Packaging templates must not hardcode a version any more.
    for template in (
        ROOT / "packaging" / "windows" / "haluro_installer.iss.in",
        ROOT / "packaging" / "windows" / "version_info.txt.in",
    ):
        stale: list[str] = []
        for line in template.read_text(encoding="utf-8").splitlines():
            if "MinVersion" in line:
                continue  # Windows build number, not an application version
            stale.extend(s for s in re.findall(r"\b\d+\.\d+\.\d+\b", line) if s != version)
        if stale:
            problems.append(f"{template.name} contiene versiones fijas: {stale}")

    # The macOS script must resolve the version dynamically.
    macos_script = (ROOT / "packaging" / "macos" / "build_macos.sh").read_text(encoding="utf-8")
    if "from engine import __version__" not in macos_script:
        problems.append("build_macos.sh no resuelve la versión desde engine/__init__.py")

    if problems:
        print("\n✗ Versión inconsistente:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"✓ Versión {version} consistente en todo el repositorio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
