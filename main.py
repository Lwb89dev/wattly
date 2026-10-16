"""Android entry point (python-for-android webview bootstrap).

The WebView activity loads http://127.0.0.1:5055/ as soon as something
answers on that port; this script is that something. It runs the very
same Flask app as the desktop build — templates, static assets, SQLite
archive, import pipeline — served by waitress on the loopback interface.
Data lives in the app-private storage dir (WATTLY_DATA_DIR), so no
storage permission is needed.
"""

from __future__ import annotations

import os
import sys

PORT = int(os.environ.get("WATTLY_PORT", "5055"))


def _prepare_environment() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    base = os.environ.get("ANDROID_PRIVATE") or os.environ.get("ANDROID_ARGUMENT") or here
    data_dir = os.path.join(base, "wattly-data")
    os.makedirs(data_dir, exist_ok=True)
    os.environ.setdefault("WATTLY_DATA_DIR", data_dir)
    # No tesseract binary on-device: OCR is reported unavailable and the
    # pipeline falls back to raw text extraction (same as desktop without
    # tesseract installed).
    os.environ.setdefault("WATTLY_OCR", "0")


def main() -> None:
    _prepare_environment()

    from waitress import serve

    from wattly.app import create_app
    from wattly.config import load_config

    app = create_app(load_config())
    serve(app, host="127.0.0.1", port=PORT, threads=8, channel_timeout=120,
          cleanup_interval=30)


if __name__ == "__main__":
    main()
