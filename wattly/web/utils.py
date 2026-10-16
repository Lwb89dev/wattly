"""Shared web helpers: sessions, settings, flash + JSON responses."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from flask import current_app, g, jsonify

from wattly.database.db import Database
from wattly.database.repositories import SettingsRepository
from wattly.web.i18n import gettext  # re-exported for routes/forms

DEFAULT_SETTINGS: dict[str, str] = {
    "currency": "EUR",
    "locale": "it",
    "theme": "auto",  # auto | light | dark
    "ocr_enabled": "1",
    "language": "",  # empty = auto-detect (env WATTLY_LANGUAGE > OS locale)
}


def get_db() -> Database:
    return current_app.extensions["wattly_db"]


def get_config():
    return current_app.extensions["wattly_config"]


@contextmanager
def session_scope() -> Iterator:
    """Yield a DB session; commit on success, rollback on error, always close."""
    session = get_db().session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def load_settings() -> dict[str, str]:
    """Per-request settings (cached on flask.g), merged over defaults."""
    if "wattly_settings" not in g:
        from wattly.web.i18n import detect_language

        with session_scope() as s:
            stored = SettingsRepository(s).all()
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in stored.items() if v is not None})
        merged["_stored_language"] = stored.get("language") or ""
        merged["language"] = detect_language(merged.get("language"))
        g.wattly_settings = merged
        g.wattly_language = merged["language"]
    return g.wattly_settings


def save_settings(updates: dict[str, str]) -> None:
    with session_scope() as s:
        repo = SettingsRepository(s)
        for key, value in updates.items():
            repo.set(key, value)
    g.pop("wattly_settings", None)


def ocr_enabled() -> bool:
    return load_settings().get("ocr_enabled", "1") == "1"


def json_error(message: str, status: int = 400, **extra: Any):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def json_ok(**payload: Any):
    data = {"ok": True}
    data.update(payload)
    return jsonify(data)
