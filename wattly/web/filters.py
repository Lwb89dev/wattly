"""Jinja template filters (locale-aware, driven by user settings)."""

from __future__ import annotations

from datetime import date, datetime

from flask import g

CURRENCY_SYMBOLS = {
    "EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF", "JPY": "¥",
}


def _locale() -> str:
    return getattr(g, "wattly_settings", {}).get("locale", "it")


def _currency() -> str:
    return getattr(g, "wattly_settings", {}).get("currency", "EUR")


def fmt_number(value: float | int | None, nd: int = 1) -> str:
    if value is None:
        return "—"
    s = f"{value:,.{nd}f}"
    if _locale() == "it":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_money(cents: int | None, currency: str | None = None) -> str:
    if cents is None:
        return "—"
    code = (currency or _currency()).upper()
    symbol = CURRENCY_SYMBOLS.get(code, code)
    amount = cents / 100.0
    s = f"{amount:,.2f}"
    if _locale() == "it":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} {symbol}" if _locale() == "it" else f"{symbol}{s}"


def fmt_date(value: date | datetime | None, fmt: str = "%d %b %Y") -> str:
    if value is None:
        return "—"
    return value.strftime(fmt)


def fmt_date_iso(value: date | datetime | None) -> str:
    return value.isoformat() if value else ""


def fmt_pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{fmt_number(value, 1)}%"


def fmt_per_kwh(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{fmt_number(value, 4)} €/kWh"


def register_filters(app) -> None:
    app.template_filter("money")(fmt_money)
    app.template_filter("num")(fmt_number)
    app.template_filter("date")(fmt_date)
    app.template_filter("dateiso")(fmt_date_iso)
    app.template_filter("pct")(fmt_pct)
    app.template_filter("per_kwh")(fmt_per_kwh)
    app.template_filter("d")(lambda v, f: v.strftime(f) if v else "")
