"""Flask application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, g, render_template, request

from wattly import __version__
from wattly.config import Config, load_config
from wattly.database.db import Database
from wattly.web import filters
from wattly.web.routes import register_blueprints
from wattly.web.utils import load_settings

logger = logging.getLogger("wattly")

NAV_ITEMS = [
    ("dashboard.index", "nav.dashboard", "grid"),
    ("import.index", "nav.import", "upload"),
    ("bills.history", "nav.history", "files"),
    ("analytics.index", "nav.analytics", "chart"),
    ("compare.index", "nav.compare", "swap"),
    ("export.index", "nav.export", "download"),
    ("settings.index", "nav.settings", "gear"),
]


def create_app(config: Config | None = None) -> Flask:
    base = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(base / "web" / "templates"),
        static_folder=str(base / "web" / "static"),
    )
    cfg = config or load_config()
    cfg.documents_dir.mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        MAX_CONTENT_LENGTH=cfg.max_content_length,
    )
    app.extensions["wattly_config"] = cfg

    database = Database(cfg)
    database.migrate()
    if not database.healthcheck():
        raise RuntimeError(f"Database not reachable at {cfg.database_url}")
    app.extensions["wattly_db"] = database

    filters.register_filters(app)
    register_blueprints(app)
    # Be liberal about trailing slashes (/analytics == /analytics/).
    app.url_map.strict_slashes = False

    @app.before_request
    def _preload_settings() -> None:
        if request.endpoint != "static":
            load_settings()

    @app.context_processor
    def _inject_globals():
        from wattly.web import i18n

        language = load_settings().get("language", "en")
        return {
            "app_version": __version__,
            "nav_items": NAV_ITEMS,
            "settings": load_settings(),
            "t": i18n.gettext,
            "js_i18n": i18n.js_catalog(language),
        }

    @app.errorhandler(404)
    def _not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def _too_large(_e):
        from flask import flash, redirect, url_for
        from wattly.web.utils import gettext

        flash(gettext("flash.file_too_large", n=cfg.max_upload_mb), "error")
        return redirect(url_for("import.index"))

    @app.errorhandler(500)
    def _server_error(e):
        logger.exception("Unhandled error: %s", e)
        try:
            return render_template("errors/500.html"), 500
        except Exception:
            return "Internal error", 500

    @app.cli.command("demo-data")
    def cli_demo_data():
        """Insert the deterministic demo dataset."""
        from wattly.services.demo_data import generate_demo_bills

        session = database.session()
        try:
            n = generate_demo_bills(session)
            session.commit()
            print(f"Inserted {n} demo bills.")
        finally:
            session.close()

    @app.cli.command("make-samples")
    def cli_make_samples():
        """Write sample bill PDFs into the data directory."""
        from wattly.samples import build_sample_pdfs

        out = cfg.data_dir / "samples"
        paths = build_sample_pdfs(out)
        for p in paths:
            print(p)

    @app.teardown_appcontext
    def _cleanup(_exc=None):
        g.pop("wattly_settings", None)

    return app
