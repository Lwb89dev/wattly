"""Settings screen + demo-data + theme toggle + update-check endpoints."""

from __future__ import annotations

from flask import (
    Blueprint, flash, redirect, render_template, request, url_for,
)

from wattly import __version__
from wattly.parsing.ocr_engine import ocr_available
from wattly.services.demo_data import generate_demo_bills
from wattly.web.utils import (
    get_config, gettext, json_error, json_ok, load_settings, save_settings, session_scope,
)

bp = Blueprint("settings", __name__, url_prefix="/settings")

CURRENCIES = ["EUR", "USD", "GBP", "CHF", "JPY"]
LOCALES = [("it", "Italian format (1.234,56)"), ("en", "International (1,234.56)")]


def _render(update_info: dict | None = None):
    ocr_ok, ocr_reason = ocr_available()
    with session_scope() as s:
        from wattly.database.repositories import BillRepository, DocumentRepository

        bill_count = BillRepository(s).count()
        doc_count = len(DocumentRepository(s).recent(1000))
    cfg = get_config()
    return render_template(
        "settings.html",
        settings=load_settings(),
        currencies=CURRENCIES, locales=LOCALES,
        ocr_ok=ocr_ok, ocr_reason=ocr_reason,
        bill_count=bill_count, doc_count=doc_count,
        data_dir=str(cfg.data_dir),
        update_info=update_info,
        capability=update_capability(),
    )


def update_capability() -> str:
    """Updater capability exposed to the template (hint/button labelling)."""
    from wattly.services import updater

    return updater.update_capability()


@bp.route("", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        updates = {
            "currency": (request.form.get("currency") or "EUR").upper()[:3],
            "locale": request.form.get("locale") or "it",
            "theme": request.form.get("theme") or "auto",
            "ocr_enabled": "1" if request.form.get("ocr_enabled") == "1" else "0",
        }
        if "language" in request.form:
            updates["language"] = (request.form.get("language") or "").strip().lower()[:2]
        save_settings(updates)
        flash(gettext("flash.settings_saved"), "success")
        return redirect(url_for("settings.index"))

    return _render()


@bp.post("/update-check")
def update_check():
    """Server-side update check (works in every mode, incl. the browser)."""
    from wattly.services import updater

    if updater.update_capability() == "none":
        flash(gettext("flash.update_unsupported"), "info")
        return _render()

    try:
        release = updater.fetch_latest_release()
    except updater.UpdateError as exc:
        flash(gettext("flash.update_check_failed", err=exc), "error")
        return _render()

    if updater.is_newer(release.version, __version__):
        flash(gettext("flash.update_available", v=release.version), "info")
        return _render({"version": release.version, "url": release.page_url})

    flash(gettext("flash.update_latest", v=__version__), "success")
    return _render()


@bp.post("/theme")
def theme():
    value = (request.form.get("theme") or "").lower()
    if value in {"light", "dark", "auto"}:
        save_settings({"theme": value})
        return json_ok(theme=value)
    from wattly.web.utils import json_error

    return json_error("Invalid theme.")


@bp.post("/demo")
def demo():
    with session_scope() as s:
        n = generate_demo_bills(s)
    if n:
        flash(gettext("flash.demo_loaded", n=n), "success")
    else:
        flash(gettext("flash.demo_already"), "info")
    return redirect(url_for("dashboard.index"))
