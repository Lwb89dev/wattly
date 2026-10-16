"""Unit tests for the GitHub self-updater decision logic."""

from __future__ import annotations

import io
import json

import pytest

from wattly import __version__
from wattly.services import updater


class _FakeResponse:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.headers = headers or {}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release_payload(tag="v1.2.3", assets=None):
    return {
        "tag_name": tag,
        "html_url": "https://github.com/Lwb89dev/wattly/releases/tag/" + tag,
        "body": "notes",
        "assets": assets or [],
    }


# --------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------- #

def test_normalize_version_strips_leading_v():
    assert updater.normalize_version("v1.2.3") == "1.2.3"
    assert updater.normalize_version("V10.0.1") == "10.0.1"
    assert updater.normalize_version("1.0.0") == "1.0.0"


def test_is_newer_basic():
    assert updater.is_newer("1.0.0", "0.1.0")
    assert updater.is_newer("v2.0.0", "1.9.9")
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("0.9.0", "1.0.0")


def test_is_newer_pads_missing_components():
    assert updater.is_newer("1.0.1", "1.0")
    assert not updater.is_newer("1.0", "1.0.0")


def test_is_newer_prereleases_sort_below_release():
    assert updater.is_newer("1.0.0", "1.0.0-rc1")
    assert updater.is_newer("1.0.0-rc2", "1.0.0-rc1")
    assert updater.is_newer("1.0.0-rc1", "0.9.0")
    assert not updater.is_newer("1.0.0-rc1", "1.0.0")


# --------------------------------------------------------------------- #
# release parsing / fetch
# --------------------------------------------------------------------- #

def test_fetch_latest_release_parses_assets():
    payload = _release_payload("v1.2.3", assets=[
        {"name": "wattly.exe", "browser_download_url": "https://x/wattly.exe", "size": 10},
        {"name": "wattly_amd64.deb", "browser_download_url": "https://x/wattly.deb", "size": 20},
    ])
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return _FakeResponse(payload)

    release = updater.fetch_latest_release(urlopen=fake_urlopen)
    assert release.version == "1.2.3"
    assert release.tag == "v1.2.3"
    assert len(release.assets) == 2
    assert release.assets[1].size == 20
    assert "Lwb89dev/wattly" in seen["url"]


def test_fetch_latest_release_raises_update_error():
    def fake_urlopen(req, timeout=None):
        raise OSError("boom")

    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release(urlopen=fake_urlopen)


def test_fetch_latest_release_releases_without_tag():
    def fake_urlopen(req, timeout=None):
        return _FakeResponse({"tag_name": ""})

    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release(urlopen=fake_urlopen)


# --------------------------------------------------------------------- #
# asset selection
# --------------------------------------------------------------------- #

def _assets():
    return [
        updater.ReleaseAsset("wattly-1.0.0-windows.exe", "https://x/w.exe"),
        updater.ReleaseAsset("wattly_1.0.0_amd64.deb", "https://x/w.deb"),
        updater.ReleaseAsset("wattly_1.0.0_arm64.deb", "https://x/wa.deb"),
        updater.ReleaseAsset("checksums.txt", "https://x/sums.txt"),
    ]


def test_pick_asset_windows_prefers_exe():
    asset = updater.pick_asset(_assets(), "win32", "AMD64")
    assert asset.name.endswith(".exe")


def test_pick_asset_linux_arch_specific():
    assert updater.pick_asset(_assets(), "linux", "x86_64").name == "wattly_1.0.0_amd64.deb"
    assert updater.pick_asset(_assets(), "linux", "aarch64").name == "wattly_1.0.0_arm64.deb"


def test_pick_asset_linux_falls_back_to_first():
    asset = updater.pick_asset(_assets(), "linux", "riscv64")
    assert asset.name.endswith(".deb")


def test_pick_asset_none_for_unknown_platform():
    assert updater.pick_asset(_assets(), "haiku", "x86_64") is None
    assert updater.pick_asset([], "linux", "x86_64") is None


# --------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------- #

def test_download_asset_writes_chunks_and_reports_progress(tmp_path):
    payload = b"0123456789" * 100  # 1000 bytes
    progress = []

    def fake_urlopen(req, timeout=None):
        return _BytesResp(payload, headers={"Content-Length": str(len(payload))})

    dest = updater.download_asset(
        updater.ReleaseAsset("w.bin", "https://x/w.bin"),
        tmp_path,
        progress=lambda done, total: progress.append((done, total)),
        urlopen=fake_urlopen,
    )
    assert dest.read_bytes() == payload
    assert progress and progress[-1] == (1000, 1000)


class _BytesResp:
    def __init__(self, data: bytes, headers: dict | None = None):
        self._buf = io.BytesIO(data)
        self.headers = headers or {}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------------------- #
# capability
# --------------------------------------------------------------------- #

def test_capability_on_dev_host_is_browser_or_full():
    assert updater.update_capability() in {"browser", "full"}


def test_is_android_detects_p4a_env(monkeypatch):
    monkeypatch.setattr(updater.sys, "getandroidapilevel", 30, raising=False)
    assert updater.is_android()
    assert updater.update_capability() == "none"


# --------------------------------------------------------------------- #
# settings route (web integration)
# --------------------------------------------------------------------- #

def test_settings_update_check_latest(client, monkeypatch):
    monkeypatch.setattr(
        updater, "fetch_latest_release",
        lambda *a, **k: updater.ReleaseInfo(version=__version__, tag="v" + __version__,
                                            page_url="https://x", notes=""),
    )
    resp = client.post("/settings/update-check")
    assert resp.status_code == 200
    assert b"up to date" in resp.data


def test_settings_update_check_available(client, monkeypatch):
    monkeypatch.setattr(
        updater, "fetch_latest_release",
        lambda *a, **k: updater.ReleaseInfo(version="99.0.0", tag="v99.0.0",
                                            page_url="https://github.com/Lwb89dev/wattly/releases",
                                            notes=""),
    )
    resp = client.post("/settings/update-check")
    assert resp.status_code == 200
    assert b"99.0.0" in resp.data
    assert b"https://github.com/Lwb89dev/wattly/releases" in resp.data


def test_settings_update_check_failure(client, monkeypatch):
    def boom(*a, **k):
        raise updater.UpdateError("offline")

    monkeypatch.setattr(updater, "fetch_latest_release", boom)
    resp = client.post("/settings/update-check")
    assert resp.status_code == 200
    assert b"offline" in resp.data
