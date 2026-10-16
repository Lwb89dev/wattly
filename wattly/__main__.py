"""Entry point: ``python -m wattly [--server] [--debug] [--port N]``.

Default mode launches the pywebview desktop window; falls back to a
plain browser-served Flask app when pywebview cannot start (e.g. no
display server or missing GTK).
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="wattly", description="Wattly — electricity bill analytics")
    parser.add_argument("--server", action="store_true", help="run as a local web server (no desktop window)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--make-samples", action="store_true", help="generate sample bill PDFs and exit")
    args = parser.parse_args()

    from wattly.config import load_config

    cfg = load_config()
    if args.debug:
        cfg.debug = True

    if args.make_samples:
        from wattly.samples import build_sample_pdfs

        out = cfg.data_dir / "samples"
        for path in build_sample_pdfs(out):
            print(path)
        return 0

    from wattly.app import create_app

    app = create_app(cfg)

    if not args.server:
        try:
            from wattly.desktop.webview_app import run_desktop

            run_desktop(app)
            return 0
        except Exception as exc:  # ImportError, no display, missing GTK...
            print(f"Desktop mode unavailable ({exc}); falling back to server mode.",
                  file=sys.stderr)
            print(f"Open http://{args.host}:{args.port} in your browser.", file=sys.stderr)

    app.run(host=args.host, port=args.port, debug=cfg.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
