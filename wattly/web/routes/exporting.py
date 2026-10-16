"""Export screen + download endpoints (CSV / XLSX)."""

from __future__ import annotations

from flask import Blueprint, Response, flash, redirect, render_template, request, session as flask_session, url_for

from wattly.core import comparisons
from wattly.core.analytics import build_report
from wattly.services import export_service
from wattly.services.bill_service import BillService
from wattly.web.utils import gettext, session_scope

bp = Blueprint("export", __name__, url_prefix="/export")


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        text, mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _bytes_response(data: bytes, filename: str, mime: str) -> Response:
    return Response(
        data, mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.get("")
def index():
    with session_scope() as s:
        svc = BillService(s)
        count = svc.repo.count()
    last = flask_session.get("last_compare")
    return render_template("export.html", bill_count=count, last_compare=last)


def _comparison_from_session(bills):
    """Rebuild the last ComparisonResult from the session, or None."""
    params = flask_session.get("last_compare")
    if not params:
        return None
    bills_a, label_a = comparisons.select(bills, params["kind_a"], params["value_a"])
    bills_b, label_b = comparisons.select(bills, params["kind_b"], params["value_b"])
    return comparisons.compare(
        comparisons.aggregate(bills_a, label_a),
        comparisons.aggregate(bills_b, label_b),
    )


@bp.get("/download")
def download():
    what = request.args.get("what", "bills")
    fmt = request.args.get("fmt", "csv")
    with session_scope() as s:
        bills = BillService(s).all_confirmed()
        report = build_report(bills)

        if what == "bills":
            if fmt == "xlsx":
                comp = _comparison_from_session(bills)
                data = export_service.workbook_xlsx(bills, report, comp)
                return _bytes_response(data, "wattly_bills.xlsx",
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return _csv_response(export_service.bills_csv(bills), "wattly_bills.csv")

        if what == "monthly":
            return _csv_response(export_service.monthly_csv(report), "wattly_monthly.csv")

        if what == "comparison":
            res = _comparison_from_session(bills)
            if res is None:
                flash(gettext("flash.comparison_first"), "error")
                return redirect(url_for("export.index"))
            return _csv_response(export_service.comparison_csv(res), "wattly_comparison.csv")

    flash(gettext("flash.unknown_export"), "error")
    return redirect(url_for("export.index"))
