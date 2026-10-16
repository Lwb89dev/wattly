"""pywebview glue for the self-updater.

Owns everything the pure :mod:`wattly.services.updater` deliberately does
not: native dialogs, the progress overlay injected into the page, the
platform-specific install step and the relaunch. The check is reachable
with **Ctrl+Shift+U** in the desktop window, or from Settings → Updates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from wattly import __version__
from wattly.services import updater
from wattly.web.i18n import detect_language, gettext

#: Injected after the page loads: binds Ctrl+Shift+U and provides the
#: progress overlay used while the new build downloads.
UPDATER_JS = r"""
(function () {
  if (window.__wattlyUpdaterBound) return;
  window.__wattlyUpdaterBound = true;
  function ensureOverlay() {
    var ov = document.getElementById('wattly-update-overlay');
    if (ov) return ov;
    ov = document.createElement('div');
    ov.id = 'wattly-update-overlay';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(8,12,20,.7);z-index:99999;' +
      'display:none;align-items:center;justify-content:center;';
    var box = document.createElement('div');
    box.style.cssText = 'background:#141a26;color:#e8ecf4;padding:26px 32px;border-radius:14px;' +
      'font:15px system-ui,sans-serif;box-shadow:0 14px 44px rgba(0,0,0,.5);' +
      'text-align:center;min-width:300px;max-width:80vw;';
    var label = document.createElement('div');
    label.id = 'wattly-update-label';
    label.style.marginBottom = '14px';
    var track = document.createElement('div');
    track.style.cssText = 'height:8px;background:rgba(127,140,160,.28);border-radius:99px;overflow:hidden;';
    var bar = document.createElement('div');
    bar.id = 'wattly-update-bar';
    bar.style.cssText = 'height:100%;width:0%;background:#2563eb;transition:width .2s;';
    track.appendChild(bar);
    box.appendChild(label);
    box.appendChild(track);
    ov.appendChild(box);
    document.body.appendChild(ov);
    return ov;
  }
  window.__wattlyUpdateProgress = function (pct, label) {
    var ov = ensureOverlay();
    ov.style.display = 'flex';
    document.getElementById('wattly-update-bar').style.width =
      Math.max(0, Math.min(100, pct)) + '%';
    if (label) document.getElementById('wattly-update-label').textContent = label;
  };
  window.__wattlyUpdateHide = function () {
    var ov = document.getElementById('wattly-update-overlay');
    if (ov) ov.style.display = 'none';
  };
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'u' || e.key === 'U')) {
      e.preventDefault();
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.check_and_update();
      }
    }
  });
})();
"""


class UpdaterApi:
    """Exposed to JS as ``window.pywebview.api``."""

    def __init__(self) -> None:
        self.window = None  # set by run_desktop right after create_window
        self._busy = threading.Lock()

    # Called from JS (Ctrl+Shift+U or the Settings button).
    def check_and_update(self) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            self._flow()
        except Exception as exc:  # never let a dialog crash the window
            try:
                self._alert(f"Update error: {exc}")
            except Exception:
                pass
        finally:
            self._busy.release()

    # ------------------------------------------------------------------ #
    def _flow(self) -> None:
        lang = detect_language()

        def T(key: str, **kw) -> str:
            return gettext(key, lang, **kw)

        try:
            release = updater.fetch_latest_release()
        except updater.UpdateError as exc:
            self._alert(T("dlg.update_network", err=exc))
            return

        if not updater.is_newer(release.version, __version__):
            self._alert(T("dlg.update_up_to_date", v=__version__))
            return

        proceed = self.window.create_confirmation_dialog(
            T("dlg.update_title"),
            T("dlg.update_available", v=release.version, cur=__version__),
        )
        if not proceed:
            return

        if updater.update_capability() != "full":
            webbrowser.open(release.page_url)
            self._alert(T("dlg.update_manual"))
            return

        asset = release.asset_for()
        if asset is None:
            webbrowser.open(release.page_url)
            self._alert(T("dlg.update_no_asset"))
            return

        try:
            dest = updater.download_asset(
                asset, Path(tempfile.mkdtemp(prefix="wattly-update-")),
                progress=self._progress(T("dlg.update_downloading")),
            )
        except updater.UpdateError as exc:
            self._alert(T("dlg.update_failed", err=exc))
            return

        try:
            action, detail = install_download(dest)
        except Exception as exc:
            self._alert(T("dlg.update_failed", err=exc))
            return

        if action == "restart":
            self._alert(T("dlg.update_restarting"))
            relaunch_and_exit(self.window)
        else:
            self._alert(T("dlg.update_downloaded", path=detail))

    # ------------------------------------------------------------------ #
    def _alert(self, message: str) -> None:
        self.window.create_alert_dialog("Wattly", message)

    def _progress(self, label: str):
        def cb(done: int, total: int) -> None:
            pct = (done * 100 // total) if total else 0
            try:
                self.window.evaluate_js(
                    "window.__wattlyUpdateProgress && window.__wattlyUpdateProgress"
                    f"({pct}, {json.dumps(label)});"
                )
            except Exception:
                pass

        return cb


def install_download(path: Path) -> tuple[str, str]:
    """Install ``path`` (the downloaded build). Returns (action, detail):
    ("restart", "") when the app will relaunch itself, ("manual", path)
    when the user must finish the installation."""
    if sys.platform.startswith("win"):
        target = Path(sys.executable)
        batch = path.with_name("wattly-update.bat")
        batch.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            ":wait\r\n"
            f'tasklist /FI "IMAGENAME eq {target.name}" 2>NUL | find /I "{target.name}" >NUL\r\n'
            "if %ERRORLEVEL%==0 (timeout /t 1 /nobreak >nul & goto wait)\r\n"
            f'move /y "{path}" "{target}"\r\n'
            f'start "" "{target}"\r\n'
            "del \"%~f0\"\r\n",
            encoding="ascii",
        )
        subprocess.Popen(["cmd", "/c", str(batch)],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                         close_fds=True)
        return "restart", ""

    if sys.platform.startswith("linux"):
        if path.suffix == ".deb":
            for runner in (["pkexec", "dpkg", "-i", str(path)],
                           ["sudo", "-n", "dpkg", "-i", str(path)]):
                if shutil.which(runner[0]):
                    result = subprocess.run(runner)
                    if result.returncode == 0:
                        return "restart", ""
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        dest = downloads / path.name
        shutil.copy2(path, dest)
        return "manual", str(dest)

    return "manual", str(path)


def relaunch_and_exit(window) -> None:
    """Give dialogs a moment to render, then close the window and exit;
    the platform installer (or the fresh deb binary) restarts the app."""

    def _quit() -> None:
        time.sleep(1.5)
        try:
            window.evaluate_js("window.__wattlyUpdateHide && window.__wattlyUpdateHide();")
            window.destroy()
        except Exception:
            pass
        time.sleep(1.0)
        if sys.platform.startswith("linux") and shutil.which("wattly"):
            try:
                subprocess.Popen(["wattly"], start_new_session=True)
            except Exception:
                pass
        os._exit(0)

    threading.Thread(target=_quit, daemon=True).start()


def updater_js() -> str:
    return UPDATER_JS
