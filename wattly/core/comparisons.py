"""Comparison engine: periods, seasons, providers, custom ranges.

Selectors are resolved to lists of matching bills; aggregates are
computed day-weighted so unequal-length periods compare fairly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from wattly.core.models import Bill

SEASONS = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}


@dataclass
class PeriodAggregate:
    label: str
    bills: list[Bill] = field(default_factory=list)
    kwh: float = 0.0
    cents: int = 0
    days: int = 0
    daily_kwh: float = 0.0
    cost_per_kwh: float | None = None
    band_kwh: dict[str, float] = field(default_factory=dict)


@dataclass
class ComparisonResult:
    kind: str
    label_a: str
    label_b: str
    a: PeriodAggregate
    b: PeriodAggregate
    kwh_delta: float = 0.0
    kwh_delta_pct: float | None = None
    cost_delta_cents: int = 0
    cost_delta_pct: float | None = None
    cost_per_kwh_delta: float | None = None
    daily_kwh_delta: float = 0.0
    daily_kwh_delta_pct: float | None = None


def aggregate(bills: list[Bill], label: str) -> PeriodAggregate:
    agg = PeriodAggregate(label=label)
    for b in bills:
        if b.total_kwh is None or b.total_amount_cents is None:
            continue
        days = b.period_days() or 30
        agg.bills.append(b)
        agg.kwh += b.total_kwh
        agg.cents += b.total_amount_cents
        agg.days += days
        for band in b.time_bands:
            if band.label:
                agg.band_kwh[band.label] = agg.band_kwh.get(band.label, 0.0) + (band.kwh or 0.0)
    agg.kwh = round(agg.kwh, 1)
    agg.daily_kwh = round(agg.kwh / agg.days, 3) if agg.days else 0.0
    agg.cost_per_kwh = round(agg.cents / 100.0 / agg.kwh, 4) if agg.kwh else None
    agg.band_kwh = {k: round(v, 1) for k, v in agg.band_kwh.items()}
    return agg


def _pct(old: float, new: float) -> float | None:
    return round((new - old) / old * 100.0, 1) if old else None


def compare(agg_a: PeriodAggregate, agg_b: PeriodAggregate, kind: str = "period") -> ComparisonResult:
    """Compare B against A (deltas = B - A)."""
    res = ComparisonResult(
        kind=kind, label_a=agg_a.label, label_b=agg_b.label, a=agg_a, b=agg_b
    )
    res.kwh_delta = round(agg_b.kwh - agg_a.kwh, 1)
    res.kwh_delta_pct = _pct(agg_a.kwh, agg_b.kwh)
    res.cost_delta_cents = agg_b.cents - agg_a.cents
    res.cost_delta_pct = _pct(agg_a.cents, agg_b.cents)
    if agg_a.cost_per_kwh is not None and agg_b.cost_per_kwh is not None:
        res.cost_per_kwh_delta = round(agg_b.cost_per_kwh - agg_a.cost_per_kwh, 4)
    res.daily_kwh_delta = round(agg_b.daily_kwh - agg_a.daily_kwh, 3)
    res.daily_kwh_delta_pct = _pct(agg_a.daily_kwh, agg_b.daily_kwh)
    return res


def select(bills: list[Bill], kind: str, value: str) -> tuple[list[Bill], str]:
    """Resolve a selector into (matching bills, display label).

    ``kind`` is one of: month (YYYY-MM), quarter (YYYY-Q1..4), year (YYYY),
    season (winter|spring|summer|autumn[:YYYY]), range (ISO start:end),
    provider (case-insensitive name substring).
    """
    key = lambda b: b.billing_period_start or b.issue_date  # noqa: E731

    if kind == "month":
        target = value
        match = [b for b in bills if key(b) and key(b).strftime("%Y-%m") == target]
        y, m = target.split("-")
        label = date(int(y), int(m), 1).strftime("%b %Y")
    elif kind == "quarter":
        clean = value.upper().replace("Q", "").strip()
        year_s, q_s = clean.split("-")
        year, q = int(year_s), int(q_s)
        months = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}[q]
        match = [
            b for b in bills
            if key(b) and key(b).year == year and months[0] <= key(b).month <= months[1]
        ]
        label = f"Q{q} {year}"
    elif kind == "year":
        year = int(value)
        match = [b for b in bills if key(b) and key(b).year == year]
        label = str(year)
    elif kind == "season":
        parts = value.split(":")
        season = parts[0].lower()
        year = int(parts[1]) if len(parts) > 1 and parts[1] else None
        months = SEASONS.get(season, SEASONS["summer"])
        if year:
            match = [
                b for b in bills
                if key(b) and key(b).year == year and key(b).month in months
            ]
            label = f"{season.capitalize()} {year}"
        else:  # all data: aggregate across years by season months
            match = [b for b in bills if key(b) and key(b).month in months]
            label = f"{season.capitalize()} (all years)"
    elif kind == "range":
        start_s, _, end_s = value.partition(":")
        start = date.fromisoformat(start_s)
        end = date.fromisoformat(end_s)
        match = [b for b in bills if key(b) and start <= key(b) <= end]
        label = f"{start:%d %b %Y} – {end:%d %b %Y}"
    elif kind == "provider":
        needle = value.strip().lower()
        match = [b for b in bills if needle in (b.provider_name or "").lower()]
        label = value.strip() or "Provider"
    else:
        match, label = [], value
    return match, label
