"""Bill form parsing: raw form data -> :class:`Bill` domain object.

Also provides prefill helpers (Bill or parse result -> form string
values) and the review-snapshot diff that marks user-corrected fields.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from wattly.core.models import Bill, TimeBand
from wattly.parsing.normalization import (
    normalize_band_label,
    parse_amount_to_cents,
    parse_date,
    parse_number,
)

DATE_FIELDS = (
    "issue_date", "billing_period_start", "billing_period_end",
    "reading_start_date", "reading_end_date",
)
AMOUNT_FIELDS = ("total_amount", "fixed_charges", "energy_charges", "taxes_and_fees")
FLOAT_FIELDS = ("total_kwh", "previous_reading", "current_reading")
OPTIONAL_STR_FIELDS = ("account_number", "pod_identifier", "tariff_type")


def _money_str(cents: int | None, locale: str = "it") -> str:
    if cents is None:
        return ""
    s = f"{cents / 100.0:.2f}"
    return s.replace(".", ",") if locale == "it" else s


def parse_bill_form(form, locale: str = "it") -> tuple[Bill, dict[str, str]]:
    """Convert submitted form data into a Bill; returns (bill, errors)."""
    from wattly.web.utils import gettext as _

    errors: dict[str, str] = {}
    bill = Bill()
    bill.provider_name = (form.get("provider_name") or "").strip()
    if not bill.provider_name:
        errors["provider_name"] = _("val.provider_required")
    for name in OPTIONAL_STR_FIELDS:
        setattr(bill, name, (form.get(name) or "").strip() or None)
    bill.currency = (form.get("currency") or "EUR").upper()[:3] or "EUR"
    bill.notes = (form.get("notes") or "").strip()

    for name in DATE_FIELDS:
        raw = (form.get(name) or "").strip()
        if not raw:
            setattr(bill, name, None)
            continue
        d = parse_date(raw)
        if d is None:
            errors[name] = _("val.bad_date", raw=raw)
        setattr(bill, name, d)
    if bill.billing_period_start is None:
        errors.setdefault("billing_period_start", _("val.period_start_required"))
    if bill.billing_period_end is None:
        errors.setdefault("billing_period_end", _("val.period_end_required"))

    for name in AMOUNT_FIELDS:
        raw = (form.get(name) or "").strip()
        if not raw:
            setattr(bill, name + "_cents", None)
            continue
        cents = parse_amount_to_cents(raw, locale)
        if cents is None:
            errors[name] = _("val.bad_amount", raw=raw)
        setattr(bill, name + "_cents", cents)
    if bill.total_amount_cents is None:
        errors.setdefault("total_amount", _("val.total_required"))

    for name in FLOAT_FIELDS:
        raw = (form.get(name) or "").strip()
        if not raw:
            setattr(bill, name, None)
            continue
        v = parse_number(raw, locale)
        if v is None:
            errors[name] = _("val.bad_number", raw=raw)
        setattr(bill, name, v)
    if bill.total_kwh is None:
        errors.setdefault("total_kwh", _("val.kwh_required"))

    bill.time_bands = _parse_bands(form, locale, errors)
    return bill, errors


def _parse_bands(form, locale: str, errors: dict[str, str]) -> list[TimeBand]:
    labels = form.getlist("band_label")
    kwhs = form.getlist("band_kwh")
    amounts = form.getlist("band_amount")
    bands: list[TimeBand] = []
    for i, raw_label in enumerate(labels):
        label_raw = (raw_label or "").strip()
        if not label_raw:
            continue
        band = TimeBand(label=normalize_band_label(label_raw) or label_raw[:20])
        kw = (kwhs[i] if i < len(kwhs) else "").strip()
        amt = (amounts[i] if i < len(amounts) else "").strip()
        if kw:
            v = parse_number(kw, locale)
            if v is None:
                from wattly.web.utils import gettext as _

                errors[f"band_{i}"] = _("val.bad_band_kwh", raw=kw)
            else:
                band.kwh = v
        if amt:
            band.amount_cents = parse_amount_to_cents(amt, locale)
        bands.append(band)
    return bands


# --------------------------------------------------------------------- #
# Prefill helpers
# --------------------------------------------------------------------- #
def values_for_bill(bill: Bill, locale: str = "it") -> dict[str, Any]:
    """Form string values for editing an existing bill."""
    v: dict[str, Any] = {
        "provider_name": bill.provider_name or "",
        "account_number": bill.account_number or "",
        "pod_identifier": bill.pod_identifier or "",
        "tariff_type": bill.tariff_type or "",
        "currency": bill.currency or "EUR",
        "notes": bill.notes or "",
        "total_amount": _money_str(bill.total_amount_cents, locale),
        "fixed_charges": _money_str(bill.fixed_charges_cents, locale),
        "energy_charges": _money_str(bill.energy_charges_cents, locale),
        "taxes_and_fees": _money_str(bill.taxes_and_fees_cents, locale),
        "total_kwh": f"{bill.total_kwh:g}" if bill.total_kwh is not None else "",
        "previous_reading": f"{bill.previous_reading:g}" if bill.previous_reading is not None else "",
        "current_reading": f"{bill.current_reading:g}" if bill.current_reading is not None else "",
    }
    for name in DATE_FIELDS:
        d = getattr(bill, name)
        v[name] = d.isoformat() if isinstance(d, date) else ""
    v["bands"] = [
        {
            "label": b.label,
            "kwh": f"{b.kwh:g}" if b.kwh is not None else "",
            "amount": _money_str(b.amount_cents, locale),
        }
        for b in bill.time_bands
    ]
    return v


def values_for_review(result, locale: str = "it") -> dict[str, Any]:
    """Form string values + metadata from a ParsedBillResult."""
    f = result.fields
    v: dict[str, Any] = {
        "provider_name": f.get("provider_name") or "",
        "account_number": f.get("account_number") or "",
        "pod_identifier": f.get("pod_identifier") or "",
        "tariff_type": f.get("tariff_type") or "",
        "currency": "EUR",
        "notes": "",
        "total_amount": _money_str(f.get("total_amount_cents"), locale),
        "fixed_charges": _money_str(f.get("fixed_charges_cents"), locale),
        "energy_charges": _money_str(f.get("energy_charges_cents"), locale),
        "taxes_and_fees": _money_str(f.get("taxes_and_fees_cents"), locale),
        "total_kwh": f"{f.get('total_kwh'):g}" if f.get("total_kwh") is not None else "",
        "previous_reading": f"{f.get('previous_reading'):g}" if f.get("previous_reading") is not None else "",
        "current_reading": f"{f.get('current_reading'):g}" if f.get("current_reading") is not None else "",
    }
    for name in DATE_FIELDS:
        d = f.get(name)
        v[name] = d.isoformat() if isinstance(d, date) else ""
    v["bands"] = [
        {
            "label": b.label,
            "kwh": f"{b.kwh:g}" if b.kwh is not None else "",
            "amount": _money_str(b.amount_cents, locale),
        }
        for b in result.bands
    ]
    return v


# --------------------------------------------------------------------- #
# Review snapshot (session-cached parse result)
# --------------------------------------------------------------------- #
def values_for_snapshot(snap: dict, locale: str = "it") -> dict[str, Any]:
    """Form string values from a session-cached parse snapshot."""
    f = snap.get("fields", {})
    v: dict[str, Any] = {
        "provider_name": f.get("provider_name") or "",
        "account_number": f.get("account_number") or "",
        "pod_identifier": f.get("pod_identifier") or "",
        "tariff_type": f.get("tariff_type") or "",
        "currency": "EUR",
        "notes": "",
        "total_amount": _money_str(f.get("total_amount_cents"), locale),
        "fixed_charges": _money_str(f.get("fixed_charges_cents"), locale),
        "energy_charges": _money_str(f.get("energy_charges_cents"), locale),
        "taxes_and_fees": _money_str(f.get("taxes_and_fees_cents"), locale),
        "total_kwh": f"{f.get('total_kwh'):g}" if f.get("total_kwh") is not None else "",
        "previous_reading": f"{f.get('previous_reading'):g}" if f.get("previous_reading") is not None else "",
        "current_reading": f"{f.get('current_reading'):g}" if f.get("current_reading") is not None else "",
    }
    for name in DATE_FIELDS:
        d = f.get(name)
        v[name] = d if isinstance(d, str) else (d.isoformat() if isinstance(d, date) else "")
    v["bands"] = [
        {
            "label": b.get("label", ""),
            "kwh": f"{b.get('kwh'):g}" if b.get("kwh") is not None else "",
            "amount": _money_str(b.get("amount_cents"), locale),
        }
        for b in snap.get("bands", [])
    ]
    return v


SNAPSHOT_PREFIX = "wattly_review_"


def snapshot_from_result(result) -> dict[str, Any]:
    def iso(d):
        return d.isoformat() if isinstance(d, date) else d

    return {
        "fields": {k: iso(v) for k, v in result.fields.items()},
        "field_confidence": dict(result.field_confidence),
        "bands": [
            {"label": b.label, "kwh": b.kwh, "amount_cents": b.amount_cents}
            for b in result.bands
        ],
        "warnings": list(result.warnings),
        "confidence": result.confidence,
        "parse_method": result.parse_method,
        "parser_name": result.parser_name,
    }


def diff_corrected(bill: Bill, snapshot: dict[str, Any] | None) -> list[str]:
    """Field names the user changed relative to the parse snapshot."""

    def norm(v):
        return v.isoformat() if isinstance(v, date) else v

    if not snapshot:
        return []
    submitted: dict[str, Any] = {
        "provider_name": bill.provider_name,
        "account_number": bill.account_number,
        "pod_identifier": bill.pod_identifier,
        "tariff_type": bill.tariff_type,
        "issue_date": norm(bill.issue_date),
        "billing_period_start": norm(bill.billing_period_start),
        "billing_period_end": norm(bill.billing_period_end),
        "total_amount_cents": bill.total_amount_cents,
        "total_kwh": bill.total_kwh,
        "fixed_charges_cents": bill.fixed_charges_cents,
        "energy_charges_cents": bill.energy_charges_cents,
        "taxes_and_fees_cents": bill.taxes_and_fees_cents,
        "previous_reading": bill.previous_reading,
        "current_reading": bill.current_reading,
    }
    corrected: list[str] = []
    for key, parsed_val in snapshot.get("fields", {}).items():
        new_val = submitted.get(key)
        if key in submitted and parsed_val is not None and norm(new_val) != parsed_val:
            corrected.append(key)
    return corrected
