"""pywebview desktop wrapper.

Deliberately thin: starts Flask on a random localhost port in a background
thread, then opens a native window pointing at it. All real behaviour lives
in the Flask app, so the desktop shell can be replaced by any other frontend
without touching the core.

Two robustness rules learned from real usage:
  * probe for a usable GUI backend *before* starting the server — otherwise
    a failed ``webview.start()`` leaves an orphan Flask thread running;
  * build the server via ``make_server`` so it can be shut down cleanly.
"""

from __future__ import annotations

import importlib
import socket
import threading

from flask import Flask

#: (platform module, how to get it) — probed in order on every OS.
_BACKENDS = [
    ("webview.platforms.gtk", "GTK (Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1)"),
    ("webview.platforms.qt", "Qt (pip install qtpy PyQt6)"),
    ("webview.platforms.cocoa", "Cocoa (bundled on macOS)"),
    ("webview.platforms.winforms", "WinForms (bundled on Windows)"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gui_backend_probe() -> tuple[bool, str]:
    """Silently check whether pywebview has a usable GUI backend.

    Returns (available, hint-if-not). Import errors are collected, not
    printed — pywebview's own loader logs noisy tracebacks we want to avoid.
    """
    failures: list[str] = []
    for module, _hint in _BACKENDS:
        try:
            importlib.import_module(module)
            return True, ""
        except Exception as exc:  # ImportError and friends
            failures.append(f"{module.rsplit('.', 1)[-1]}: {type(exc).__name__}")
    hints = "; ".join(h for _, h in _BACKENDS[:2])
    return False, f"[{', '.join(failures)}] — install {hints} for desktop mode"


def run_desktop(app: Flask, title: str = "Wattly — Understand your energy"):
    import webview
    from werkzeug.serving import make_server

    from wattly.desktop.update_ui import UPDATER_JS, UpdaterApi

    ok, why = gui_backend_probe()
    if not ok:
        raise RuntimeError(f"no usable GUI backend {why}")

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    api = UpdaterApi()
    try:
        window = webview.create_window(
            title, f"http://127.0.0.1:{port}", width=1320, height=880, min_size=(1024, 700),
            js_api=api,
        )
        api.window = window

        def _inject_updater() -> None:
            try:
                window.evaluate_js(UPDATER_JS)
            except Exception:
                pass

        window.events.loaded += _inject_updater
        webview.start()
        return window
    finally:
        server.shutdown()
