"""Analytics engine: trends, extremes, rolling averages, anomalies.

All functions are pure: they take a sorted list of :class:`BillPoint`
and return plain dataclasses/dicts that the web layer renders directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import fmean

from wattly.core.models import Bill, BillPoint


@dataclass
class Anomaly:
    label: str
    kind: str  # "high" | "low"
    message: str
    bill_id: int | None = None


@dataclass
class AnalyticsReport:
    bill_count: int = 0
    total_kwh: float = 0.0
    total_cents: int = 0
    effective_cost_per_kwh: float | None = None
    avg_daily_kwh: float | None = None
    series: list[BillPoint] = field(default_factory=list)
    highest_kwh: BillPoint | None = None
    lowest_kwh: BillPoint | None = None
    highest_cost: BillPoint | None = None
    lowest_cost: BillPoint | None = None
    rolling_avg_kwh: list[float] = field(default_factory=list)  # aligned with series
    anomalies: list[Anomaly] = field(default_factory=list)
    band_labels: list[str] = field(default_factory=list)
    band_kwh: dict[str, float] = field(default_factory=dict)
    band_cents: dict[str, int] = field(default_factory=dict)
    yoy: list[dict] = field(default_factory=list)  # per-year aggregates


def to_points(bills: list[Bill]) -> list[BillPoint]:
    """Convert bills (sorted by period start) into time-series points."""
    points: list[BillPoint] = []
    for b in sorted(bills, key=lambda x: (x.billing_period_start or x.issue_date or date.min)):
        if b.total_kwh is None or b.total_amount_cents is None:
            continue
        days = b.period_days() or 30
        start = b.billing_period_start or b.issue_date
        if start is None:
            continue
        label = start.strftime("%b %Y")
        points.append(
            BillPoint(
                period_start=start,
                period_end=b.billing_period_end,
                label=label,
                kwh=b.total_kwh,
                amount_cents=b.total_amount_cents,
                days=days,
                bands=list(b.time_bands),
                bill_id=b.id,
            )
        )
    return points


def _rolling_avg(values: list[float], window: int = 3) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1): i + 1]
        out.append(round(fmean(chunk), 2))
    return out


def _detect_anomalies(series: list[BillPoint]) -> list[Anomaly]:
    """Flag statistically unusual months (IQR + relative-deviation test on
    per-day consumption, so short months don't trigger false positives)."""
    if len(series) < 6:
        return []
    daily = [p.daily_kwh for p in series]
    ordered = sorted(daily)
    q1 = ordered[len(ordered) // 4]
    q3 = ordered[(3 * len(ordered)) // 4]
    iqr = q3 - q1
    if iqr <= 0:
        return []
    med = fmean(daily)
    anomalies: list[Anomaly] = []
    for p, d in zip(series, daily):
        high = d > q3 + 1.5 * iqr and d > med * 1.35
        low = d < q1 - 1.5 * iqr and d < med * 0.65
        if high or low:
            anomalies.append(
                Anomaly(
                    p.label, "high" if high else "low",
                    f"Unusually {'high' if high else 'low'} consumption: {p.kwh:.0f} kWh "
                    f"({d:.2f} kWh/day vs median {med:.2f}).",
                    p.bill_id,
                )
            )
    return anomalies


def _year_aggregates(series: list[BillPoint]) -> list[dict]:
    years: dict[int, dict] = {}
    for p in series:
        y = p.period_start.year
        row = years.setdefault(y, {"year": y, "kwh": 0.0, "cents": 0, "months": 0})
        row["kwh"] += p.kwh
        row["cents"] += p.amount_cents
        row["months"] += 1
    out = []
    prev = None
    for y in sorted(years):
        row = years[y]
        row["kwh"] = round(row["kwh"], 1)
        row["cost_per_kwh"] = round(row["cents"] / 100.0 / row["kwh"], 4) if row["kwh"] else None
        row["partial"] = row["months"] < 12
        # YoY deltas are only meaningful between two complete years.
        if prev and not prev["partial"] and not row["partial"]:
            row["kwh_delta_pct"] = _pct_change(prev["kwh"], row["kwh"])
            row["cost_delta_pct"] = _pct_change(prev["cents"], row["cents"])
        out.append(row)
        prev = row
    return out


def _pct_change(old: float, new: float) -> float | None:
    if not old:
        return None
    return round((new - old) / old * 100.0, 1)


def build_report(bills: list[Bill]) -> AnalyticsReport:
    points = to_points(bills)
    rep = AnalyticsReport(bill_count=len(points))
    if not points:
        return rep
    rep.series = points
    rep.total_kwh = round(sum(p.kwh for p in points), 1)
    rep.total_cents = sum(p.amount_cents for p in points)
    rep.effective_cost_per_kwh = (
        round(rep.total_cents / 100.0 / rep.total_kwh, 4) if rep.total_kwh else None
    )
    total_days = sum(p.days for p in points)
    rep.avg_daily_kwh = round(rep.total_kwh / total_days, 3) if total_days else None
    rep.highest_kwh = max(points, key=lambda p: p.kwh)
    rep.lowest_kwh = min(points, key=lambda p: p.kwh)
    rep.highest_cost = max(points, key=lambda p: p.amount_cents)
    rep.lowest_cost = min(points, key=lambda p: p.amount_cents)
    rep.rolling_avg_kwh = _rolling_avg([p.kwh for p in points])
    rep.anomalies = _detect_anomalies(points)
    labels: list[str] = []
    for p in points:
        for band in p.bands:
            if band.label and band.label not in labels:
                labels.append(band.label)
    rep.band_labels = labels
    for lab in labels:
        rep.band_kwh[lab] = round(
            sum(b.kwh or 0.0 for p in points for b in p.bands if b.label == lab), 1
        )
        rep.band_cents[lab] = sum(
            b.amount_cents or 0 for p in points for b in p.bands if b.label == lab
        )
    rep.yoy = _year_aggregates(points)
    return rep
