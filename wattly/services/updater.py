"""Self-update against GitHub Releases.

The decision logic here is pure and unit-testable (version comparison,
release parsing, asset selection). All side effects — network access,
downloads, process replacement — are injected or live in the desktop
shell (``wattly/desktop/update_ui.py``).
"""

from __future__ import annotations

import json
import os
import platform as _platform
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

GITHUB_REPO = "Lwb89dev/wattly"
RELEASES_LATEST_URL = "https://api.github.com/repos/{repo}/releases/latest"
REQUEST_TIMEOUT = 15

_WINDOWS_EXTS = (".exe", ".msi")
_LINUX_EXTS = (".deb", ".appimage")
_MAC_EXTS = (".dmg",)

_ARCH_TOKENS = {
    "x86_64": ("amd64", "x86_64", "x64"),
    "amd64": ("amd64", "x86_64", "x64"),
    "aarch64": ("arm64", "aarch64"),
    "arm64": ("arm64", "aarch64"),
    "i386": ("i386", "i686", "x86"),
    "i686": ("i386", "i686", "x86"),
}


class UpdateError(Exception):
    """A user-friendly update failure (network, download, install)."""


@dataclass
class ReleaseAsset:
    name: str
    url: str  # browser_download_url
    size: int = 0


@dataclass
class ReleaseInfo:
    version: str  # normalized, no leading "v"
    tag: str
    page_url: str
    notes: str
    assets: list[ReleaseAsset] = field(default_factory=list)

    def asset_for(self, sys_platform: str | None = None,
                  machine: str | None = None) -> "ReleaseAsset | None":
        return pick_asset(self.assets, sys_platform, machine)


_NUM_RE = re.compile(r"(\d+)")


def normalize_version(tag: str) -> str:
    """``"v1.0.0"`` -> ``"1.0.0"``."""
    return (tag or "").strip().lstrip("vV")


def version_key(version: str) -> tuple:
    """Orderable key; a release sorts above its own pre-releases.

    ``1.0.0`` > ``1.0.0-rc1`` > ``0.9.0`` — pre-release suffixes are
    considered only when the numeric parts tie.
    """
    main, _, pre = normalize_version(version).partition("-")
    nums = tuple(int(n) for n in _NUM_RE.findall(main))
    nums = (nums + (0,) * 4)[:4]
    return (nums, 0 if pre else 1, pre)


def is_newer(remote: str, local: str) -> bool:
    """True when ``remote`` is a strictly newer version than ``local``."""
    return version_key(remote) > version_key(local)


def fetch_latest_release(repo: str = GITHUB_REPO, timeout: float = REQUEST_TIMEOUT,
                         urlopen=urllib.request.urlopen) -> ReleaseInfo:
    """Query the GitHub API for the latest release. Raises UpdateError."""
    url = RELEASES_LATEST_URL.format(repo=repo)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "wattly-updater",
    })
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(str(exc)) from exc
    tag = data.get("tag_name") or ""
    if not tag:
        raise UpdateError("release has no tag_name")
    assets = [
        ReleaseAsset(
            name=a.get("name") or "",
            url=a.get("browser_download_url") or "",
            size=int(a.get("size") or 0),
        )
        for a in (data.get("assets") or [])
    ]
    return ReleaseInfo(
        version=normalize_version(tag),
        tag=tag,
        page_url=data.get("html_url") or "",
        notes=data.get("body") or "",
        assets=assets,
    )


def pick_asset(assets: list[ReleaseAsset], sys_platform: str | None = None,
               machine: str | None = None) -> ReleaseAsset | None:
    """Choose the download for this platform: .exe on Windows, .deb on
    Linux, .dmg on macOS; arch-specific names win over generic ones."""
    sys_platform = sys_platform or sys.platform
    machine = (machine or _platform.machine() or "").lower()
    if sys_platform.startswith("win"):
        exts = _WINDOWS_EXTS
    elif sys_platform == "darwin":
        exts = _MAC_EXTS
    elif sys_platform.startswith(("linux", "android")):
        exts = _LINUX_EXTS
    else:
        exts = ()
    candidates = [a for a in assets
                  if a.url and any(a.name.lower().endswith(e) for e in exts)]
    if not candidates:
        return None
    for token in _ARCH_TOKENS.get(machine, ()):
        for asset in candidates:
            if token in asset.name.lower():
                return asset
    return candidates[0]


def download_asset(asset: ReleaseAsset, dest_dir: Path, progress=None,
                   chunk_size: int = 256 * 1024,
                   urlopen=urllib.request.urlopen) -> Path:
    """Download ``asset`` into ``dest_dir``; call ``progress(done, total)``.

    Raises UpdateError on any network/write failure.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / asset.name
    req = urllib.request.Request(asset.url, headers={"User-Agent": "wattly-updater"})
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or asset.size or 0)
            done = 0
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(str(exc)) from exc
    return dest


def is_android() -> bool:
    """True when running under python-for-android (APK)."""
    return hasattr(sys, "getandroidapilevel") or "ANDROID_ARGUMENT" in os.environ


def update_capability() -> str:
    """"full" (frozen desktop), "browser" (source install) or "none" (Android)."""
    if is_android():
        return "none"
    if getattr(sys, "frozen", False):
        return "full"
    return "browser"
