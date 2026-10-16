"""Comparison screen: two periods/providers side by side."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, render_template, request, session as flask_session

from wattly.core import comparisons
from wattly.services.bill_service import BillService
from wattly.web.utils import session_scope

bp = Blueprint("compare", __name__, url_prefix="/compare")

KINDS = [
    ("month", "cmp.kind_month"),
    ("quarter", "cmp.kind_quarter"),
    ("year", "cmp.kind_year"),
    ("season", "cmp.kind_season"),
    ("range", "cmp.kind_range"),
    ("provider", "cmp.kind_provider"),
]


def _month_options(bills) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for b in bills:
        start = b.billing_period_start or b.issue_date
        if not start:
            continue
        key = start.strftime("%Y-%m")
        label = start.strftime("%b %Y")
        if (key, label) not in seen:
            seen.append((key, label))
    return sorted(seen, reverse=True)


@bp.get("")
def index():
    with session_scope() as s:
        svc = BillService(s)
        bills = svc.all_confirmed()
        providers = svc.providers()
    months = _month_options(bills)

    if len(months) >= 2:
        default_a, default_b = months[1][0], months[0][0]
    elif len(months) == 1:
        default_a = default_b = months[0][0]
    else:
        default_a = default_b = date.today().strftime("%Y-%m")

    kind_a = request.args.get("kind_a", "month")
    kind_b = request.args.get("kind_b", "month")
    value_a = request.args.get("value_a") or default_a
    value_b = request.args.get("value_b") or default_b

    if kind_a == "range" and not request.args.get("value_a"):
        value_a = _default_range(bills, older=True)
    if kind_b == "range" and not request.args.get("value_b"):
        value_b = _default_range(bills, older=False)

    result = None
    error = None
    if bills:
        try:
            bills_a, label_a = comparisons.select(bills, kind_a, value_a)
            bills_b, label_b = comparisons.select(bills, kind_b, value_b)
            result = comparisons.compare(
                comparisons.aggregate(bills_a, label_a),
                comparisons.aggregate(bills_b, label_b),
                kind=f"{kind_a} vs {kind_b}",
            )
            flask_session["last_compare"] = {
                "kind_a": kind_a, "value_a": value_a,
                "kind_b": kind_b, "value_b": value_b,
            }
        except (ValueError, KeyError) as exc:
            error = f"Invalid comparison selection: {exc}"

    return render_template(
        "compare.html",
        kinds=KINDS,
        kind_a=kind_a, kind_b=kind_b, value_a=value_a, value_b=value_b,
        months=months, providers=providers,
        result=result, error=error, bill_count=len(bills),
    )


def _default_range(bills, older: bool) -> str:
    starts = sorted(
        (b.billing_period_start or b.issue_date) for b in bills
        if (b.billing_period_start or b.issue_date)
    )
    if not starts:
        today = date.today()
        return f"{today:%Y-%m-01}:{today:%Y-%m-%d}"
    pick = starts[0] if older else starts[-1]
    return f"{pick:%Y-%m-%d}:{pick:%Y-%m-%d}"
