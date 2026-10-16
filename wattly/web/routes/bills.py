"""Bill history, detail, manual entry, edit, delete, re-parse."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from wattly.database.repositories import DocumentRepository, LogRepository
from wattly.services.bill_service import BillService
from wattly.services.import_service import ImportService
from wattly.web import forms
from wattly.web.utils import get_config, gettext, load_settings, ocr_enabled, session_scope

bp = Blueprint("bills", __name__, url_prefix="/bills")


def _int_or_none(raw):
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _float_or_none(raw):
    try:
        return float(raw) if raw else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- #
@bp.get("")
def history():
    args = request.args
    filters = {
        "provider": args.get("provider") or None,
        "year": _int_or_none(args.get("year")),
        "month": _int_or_none(args.get("month")),
        "date_from": None, "date_to": None,
        "min_cost_cents": None, "max_cost_cents": None,
        "min_kwh": _float_or_none(args.get("min_kwh")),
        "max_kwh": _float_or_none(args.get("max_kwh")),
        "search": args.get("q") or None,
    }
    from wattly.parsing.normalization import parse_amount_to_cents, parse_date

    for key, form_key in (("date_from", "from"), ("date_to", "to")):
        raw = args.get(form_key)
        if raw:
            filters[key] = parse_date(raw)
    cost_min, cost_max = args.get("min_cost"), args.get("max_cost")
    locale = load_settings().get("locale", "it")
    if cost_min:
        filters["min_cost_cents"] = parse_amount_to_cents(cost_min, locale)
    if cost_max:
        filters["max_cost_cents"] = parse_amount_to_cents(cost_max, locale)

    with session_scope() as s:
        svc = BillService(s)
        bills = svc.list(**filters)
        providers = svc.providers()
        years = svc.years()
    return render_template(
        "bills/history.html",
        bills=bills, providers=providers, years=years,
        filters=args, count=len(bills),
    )


# --------------------------------------------------------------------- #
def _render_form(template, mode, values, errors, bill=None):
    return render_template(template, mode=mode, v=values, errors=errors, bill=bill)


EMPTY_VALUES = {
    "provider_name": "", "account_number": "", "pod_identifier": "",
    "tariff_type": "", "currency": "EUR", "notes": "",
    "total_amount": "", "fixed_charges": "", "energy_charges": "",
    "taxes_and_fees": "", "total_kwh": "", "previous_reading": "",
    "current_reading": "", "issue_date": "", "billing_period_start": "",
    "billing_period_end": "", "reading_start_date": "", "reading_end_date": "",
    "bands": [],
}


@bp.route("/new", methods=["GET", "POST"])
def new():
    locale = load_settings().get("locale", "it")
    if request.method == "POST":
        bill, errors = forms.parse_bill_form(request.form, locale)
        if not errors:
            with session_scope() as s:
                saved = BillService(s).create(bill)
            flash(gettext("flash.bill_added"), "success")
            return redirect(url_for("bills.detail", bill_id=saved.id))
        values = forms.values_for_bill(bill, locale)
        return _render_form("bills/form.html", "create", values, errors), 422
    return _render_form("bills/form.html", "create", dict(EMPTY_VALUES), {})


@bp.route("/<int:bill_id>/edit", methods=["GET", "POST"])
def edit(bill_id: int):
    locale = load_settings().get("locale", "it")
    with session_scope() as s:
        svc = BillService(s)
        bill = svc.get(bill_id)
        if bill is None:
            abort(404)
        if request.method == "POST":
            updated, errors = forms.parse_bill_form(request.form, locale)
            if not errors:
                updated.id = bill.id
                updated.document_id = bill.document_id
                updated.field_sources = dict(bill.field_sources or {})
                updated.parse_method = bill.parse_method
                updated.parse_confidence = bill.parse_confidence
                saved = svc.update(updated)
                flash(gettext("flash.bill_updated"), "success")
                return redirect(url_for("bills.detail", bill_id=saved.id))
            values = forms.values_for_bill(updated, locale)
            return _render_form("bills/form.html", "edit", values, errors, bill), 422
        values = forms.values_for_bill(bill, locale)
    return _render_form("bills/form.html", "edit", values, {}, bill)


# --------------------------------------------------------------------- #
@bp.get("/<int:bill_id>")
def detail(bill_id: int):
    with session_scope() as s:
        svc = BillService(s)
        bill = svc.get(bill_id)
        if bill is None:
            abort(404)
        logs = LogRepository(s).for_bill(bill_id)
        duplicates = svc.duplicate_warnings(bill)
        warnings = svc.validation_warnings(bill)
        doc = DocumentRepository(s).get(bill.document_id) if bill.document_id else None
    return render_template(
        "bills/detail.html", bill=bill, logs=logs, duplicates=duplicates,
        warnings=warnings, doc=doc,
    )


@bp.post("/<int:bill_id>/delete")
def delete(bill_id: int):
    with session_scope() as s:
        ok = BillService(s).delete(bill_id)
    if ok:
        flash(gettext("flash.bill_deleted"), "success")
    else:
        flash(gettext("flash.bill_not_found"), "error")
    return redirect(url_for("bills.history"))


@bp.post("/<int:bill_id>/reparse")
def reparse(bill_id: int):
    with session_scope() as s:
        svc = BillService(s)
        bill = svc.get(bill_id)
        if bill is None:
            abort(404)
        if not bill.document_id:
            flash(gettext("flash.manual_no_source"), "error")
            return redirect(url_for("bills.detail", bill_id=bill_id))
        result = ImportService(s, get_config()).parse_document(bill.document_id, ocr_enabled())
    from flask import session as flask_session

    flask_session[forms.SNAPSHOT_PREFIX + str(bill.document_id)] = forms.snapshot_from_result(result)
    if result.error:
        flash(gettext("flash.reparse_failed", err=result.error), "error")
        return redirect(url_for("bills.detail", bill_id=bill_id))
    return redirect(url_for("import.review", doc_id=bill.document_id, bill_id=bill_id))
