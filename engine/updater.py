"""Haluro in-app update checker and release discovery engine.

Fetches remote release manifest (`version.json`) from the official GitHub repository
with strict timeout (3.0s), zero telemetry, zero cookies, and graceful offline fallback.
Automatically detects the host platform (macOS Apple Silicon, macOS Intel, Windows 64-bit)
and provides direct download links tailored to the user's computer.
"""

from __future__ import annotations

import json
import logging
import platform
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from engine import __version__

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Hermesuser/haluro/main/version.json"
)
FALLBACK_RELEASES_URL = "https://github.com/Hermesuser/haluro/releases/latest"
ALLOWED_UPDATE_DOMAINS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
}


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse a semantic version string (e.g. '2.4.1', 'v2.5.0', '2.4.1-rc1') into an integer tuple.

    Ignores leading 'v'/'V', pre-release tags (-rc1), and build metadata (+build).
    """
    if not version_str:
        return (0, 0, 0)
    cleaned = version_str.strip().lstrip("vV")
    # Strip pre-release (-rc1) and build metadata (+build)
    base_ver = cleaned.split("-")[0].split("+")[0]
    tokens = base_ver.split(".")
    components: list[int] = []
    for token in tokens:
        numeric = "".join(ch for ch in token if ch.isdigit())
        if numeric:
            components.append(int(numeric))
    while len(components) < 3:
        components.append(0)
    return tuple(components[:3])


def get_client_platform() -> dict[str, str]:
    """Detect current operating system and processor architecture."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        is_arm = machine in ("arm64", "aarch64")
        return {
            "os": "macos",
            "arch": "arm64" if is_arm else "x86_64",
            "label": "macOS (Apple Silicon M1/M2/M3/M4)" if is_arm else "macOS (Intel x86_64)",
            "key": "macos_arm64" if is_arm else "macos_x86_64",
        }
    if system == "windows":
        return {
            "os": "windows",
            "arch": "x86_64",
            "label": "Windows 10/11 (64-bit)",
            "key": "windows_x86_64",
        }
    return {
        "os": "linux",
        "arch": machine,
        "label": f"Linux ({machine})",
        "key": "all_releases",
    }


def check_for_updates(
    timeout: float = 3.0,
    manifest_url: str | None = None,
) -> dict[str, Any]:
    """Check for available updates against the remote `version.json` manifest.

    Parameters
    ----------
    timeout : float
        Network timeout in seconds (default 3.0s). Never blocks the UI.
    manifest_url : str, optional
        Custom manifest URL, useful for unit tests and staging.

    Returns
    -------
    dict
        Structured update information containing:
        - `current_version`: installed version
        - `latest_version`: latest published version
        - `update_available`: boolean
        - `title`: release title
        - `release_date`: date string
        - `highlights`: list of changes/features
        - `download_url`: direct installer/dmg URL for the current platform
        - `all_releases_url`: fallback web release page
        - `platform`: human-readable platform description
        - `offline`: True if check was skipped due to network/timeout
    """
    target_url = manifest_url or DEFAULT_MANIFEST_URL
    current_ver = __version__
    plat = get_client_platform()

    default_payload: dict[str, Any] = {
        "current_version": current_ver,
        "latest_version": current_ver,
        "update_available": False,
        "offline": False,
        "platform": plat["label"],
        "download_url": FALLBACK_RELEASES_URL,
        "all_releases_url": FALLBACK_RELEASES_URL,
        "title": f"Haluro v{current_ver}",
        "release_date": "",
        "description": "",
        "highlights": [],
    }

    try:
        if target_url.startswith("file://"):
            local_path = Path(urlparse(target_url).path)
            with open(local_path, encoding="utf-8") as f:  # noqa: S310 - local file, staging only
                remote = json.load(f)
        else:
            req = urllib.request.Request(  # noqa: S310 - fixed GitHub manifest host, no credentials
                target_url,
                headers={
                    "User-Agent": f"Haluro/{current_ver} ({plat['label']})",
                    "Accept": "application/json",
                },
            )
            # The manifest host is fixed to GitHub and the request carries no credentials.
            with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
                if response.status != 200:
                    logger.info("Update check HTTP status %d", response.status)
                    default_payload["offline"] = True
                    return default_payload
                raw_bytes = response.read()
                remote = json.loads(raw_bytes.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("Update check gracefully bypassed (network offline): %s", exc)
        default_payload["offline"] = True
        return default_payload

    if not isinstance(remote, dict) or "version" not in remote:
        default_payload["offline"] = True
        return default_payload

    latest_ver = str(remote.get("version", current_ver)).strip()
    curr_parsed = parse_semver(current_ver)
    late_parsed = parse_semver(latest_ver)
    update_available = late_parsed > curr_parsed

    download_urls = remote.get("download_urls", {})
    plat_key = plat["key"]
    download_url = (
        download_urls.get(plat_key)
        or download_urls.get("all_releases")
        or FALLBACK_RELEASES_URL
    )

    return {
        "current_version": current_ver,
        "latest_version": latest_ver,
        "update_available": update_available,
        "offline": False,
        "platform": plat["label"],
        "download_url": download_url,
        "all_releases_url": download_urls.get("all_releases", FALLBACK_RELEASES_URL),
        "title": str(remote.get("title", f"Haluro v{latest_ver}")),
        "release_date": str(remote.get("release_date", "")),
        "description": str(remote.get("description", "")),
        "highlights": list(remote.get("highlights", [])),
    }


def open_external_url(url: str) -> bool:
    """Safely open an approved external URL in the system's default browser."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    domain = (parsed.netloc or "").lower().split(":")[0]
    if domain not in ALLOWED_UPDATE_DOMAINS:
        logger.warning("Refusing to open unauthorized URL: %s", url)
        return False

    try:
        return webbrowser.open(url)
    except Exception as exc:
        logger.error("Failed to open browser: %s", exc)
        return False
