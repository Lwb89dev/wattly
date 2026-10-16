"""Deterministic demo dataset.

Generates ~14 months of realistic bills (seasonal consumption curve,
F1/F2/F3 bands, provider switch mid-series so provider comparison has
something to chew on) so the dashboard is alive on first launch.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, timedelta

from sqlalchemy.orm import Session

from wattly.core import calculators
from wattly.core.models import Bill, TimeBand
from wattly.database.repositories import BillRepository

MONTHS = 14
POD = "IT001E12345678"
ACCOUNT = "40219376"
TARIFF = "Trifaria F1/F2/F3"
PRICE_PER_KWH = {"F1": 0.151, "F2": 0.143, "F3": 0.138}
BAND_SPLIT = {"F1": 0.38, "F2": 0.33, "F3": 0.29}

PROVIDER_OLD = "LuceVerde Energia S.p.A."
PROVIDER_NEW = "Elettra S.r.l."
SWITCH_AFTER = 8  # months — provider changes from the 9th month on


def _daily_kwh(year: int, month: int) -> float:
    """Seasonal daily consumption: heating in winter, cooling in summer."""
    t = 2 * math.pi * (month - 1) / 12.0
    base = 9.6 + 2.1 * math.sin(t - 2.1)  # peak around Jan, trough around Jul
    if month in (12, 1, 2):
        base += 4.2
    elif month in (6, 7, 8):
        base += 3.4
    noise = math.sin(year * 3.7 + month * 1.9) * 0.8
    return max(3.0, base + noise)


def _month_iter(n: int) -> list[tuple[int, int]]:
    today = date.today().replace(day=1)
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def generate_demo_bills(session: Session) -> int:
    repo = BillRepository(session)
    existing_periods = {
        (b.billing_period_start, b.provider_name)
        for b in repo.list(status="all")
    }
    bills: list[Bill] = []
    reading = 11842.0
    for idx, (year, month) in enumerate(_month_iter(MONTHS)):
        start = date(year, month, 1)
        days = calendar.monthrange(year, month)[1]
        end = date(year, month, days)
        if (start, PROVIDER_OLD) in existing_periods or (start, PROVIDER_NEW) in existing_periods:
            continue
        provider = PROVIDER_OLD if idx < SWITCH_AFTER else PROVIDER_NEW
        daily = _daily_kwh(year, month)
        kwh = round(daily * days, 1)
        bands = [
            TimeBand(label=lab, kwh=round(kwh * share, 1),
                     amount_cents=int(kwh * share * PRICE_PER_KWH[lab] * 100))
            for lab, share in BAND_SPLIT.items()
        ]
        energy = sum(b.amount_cents or 0 for b in bands)
        fixed = 1184 if provider == PROVIDER_OLD else 1090  # €11.84 vs €10.90
        taxes = int(kwh * 7.1) + 312  # ~€0.071/kWh transport+duties + €3.12
        total = energy + fixed + taxes
        prev_reading = reading
        reading = round(reading + kwh, 1)
        bill = Bill(
            provider_name=provider,
            account_number=ACCOUNT,
            pod_identifier=POD,
            issue_date=end + timedelta(days=4),
            billing_period_start=start,
            billing_period_end=end,
            total_amount_cents=total,
            currency="EUR",
            total_kwh=kwh,
            fixed_charges_cents=fixed,
            energy_charges_cents=energy,
            taxes_and_fees_cents=taxes,
            previous_reading=prev_reading,
            current_reading=reading,
            reading_start_date=start,
            reading_end_date=end,
            tariff_type=TARIFF,
            parse_method="demo",
            parse_confidence=1.0,
            field_sources={"dataset": "demo"},
            notes="Demo dataset bill",
            time_bands=bands,
        )
        calculators.recompute_derived(bill)
        bills.append(bill)
    for b in bills:
        repo.save(b)
    session.commit()
    return len(bills)
