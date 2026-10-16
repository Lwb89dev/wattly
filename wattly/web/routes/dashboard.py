"""Dashboard: the at-a-glance energy console."""

from __future__ import annotations

from flask import Blueprint, render_template

from wattly.database.repositories import LogRepository
from wattly.services.analytics_service import AnalyticsService
from wattly.services.bill_service import BillService
from wattly.web.utils import session_scope

bp = Blueprint("dashboard", __name__)


def _pct(old: float | None, new: float | None) -> float | None:
    if not old or new is None:
        return None
    return round((new - old) / old * 100.0, 1)


@bp.get("/")
def index():
    with session_scope() as s:
        svc = AnalyticsService(s)
        report = svc.report()
        latest = svc.latest()
        prev = svc.previous_to(latest)
        recent = BillService(s).list(status="confirmed")[-6:][::-1]
        issues = LogRepository(s).recent_issues(4)

    deltas = {
        "kwh": _pct(prev.total_kwh if prev else None, latest.total_kwh if latest else None),
        "cost": _pct(
            prev.total_amount_cents / 100 if prev and prev.total_amount_cents else None,
            latest.total_amount_cents / 100 if latest and latest.total_amount_cents else None,
        ),
        "per_kwh": _pct(
            prev.effective_total_cost_per_kwh if prev else None,
            latest.effective_total_cost_per_kwh if latest else None,
        ),
    }
    chart = {
        "labels": [p.label for p in report.series],
        "kwh": [round(p.kwh, 1) for p in report.series],
        "cost": [round(p.amount_cents / 100.0, 2) for p in report.series],
        "rolling": report.rolling_avg_kwh,
    }
    return render_template(
        "dashboard.html",
        report=report,
        latest=latest,
        prev=prev,
        deltas=deltas,
        chart=chart,
        recent=recent,
        anomalies=report.anomalies[:3],
        issues=issues,
    )
