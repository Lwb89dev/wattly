"""Analytics screen."""

from __future__ import annotations

from flask import Blueprint, render_template

from wattly.services.analytics_service import AnalyticsService
from wattly.web.utils import session_scope

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.get("")
def index():
    with session_scope() as s:
        report = AnalyticsService(s).report()
    chart = {
        "labels": [p.label for p in report.series],
        "kwh": [round(p.kwh, 1) for p in report.series],
        "cost": [round(p.amount_cents / 100.0, 2) for p in report.series],
        "rolling": report.rolling_avg_kwh,
        "perKwh": [round(p.cost_per_kwh, 4) if p.kwh else None for p in report.series],
        "bands": {
            lab: [
                round(next((b.kwh or 0.0 for b in p.bands if b.label == lab), 0.0), 1)
                for p in report.series
            ]
            for lab in report.band_labels
        },
    }
    return render_template("analytics.html", report=report, chart=chart)
