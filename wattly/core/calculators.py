"""Derived-metric calculations.

Every derived value in Wattly is computed here and nowhere else: the
service layer recomputes them on save, analytics consume them from the
domain objects. This keeps one single source of truth for the math.
"""

from __future__ import annotations

from datetime import date

from wattly.core.models import Bill


def days_inclusive(start: date | None, end: date | None) -> int | None:
    if not start or not end:
        return None
    return (end - start).days + 1


def avg_daily_kwh(total_kwh: float | None, days: int | None) -> float | None:
    if not total_kwh or not days:
        return None
    return round(total_kwh / days, 4)


def avg_cost_per_kwh(energy_charges_cents: int | None, total_kwh: float | None) -> float | None:
    """Variable-energy-only price per kWh (when components are known)."""
    if energy_charges_cents is None or not total_kwh:
        return None
    return round(energy_charges_cents / 100.0 / total_kwh, 6)


def effective_total_cost_per_kwh(total_amount_cents: int | None, total_kwh: float | None) -> float | None:
    """Whole-bill cost per kWh: total paid / total consumed."""
    if total_amount_cents is None or not total_kwh:
        return None
    return round(total_amount_cents / 100.0 / total_kwh, 6)


def recompute_derived(bill: Bill) -> Bill:
    """Recompute and store all derived metrics on the bill in place."""
    days = days_inclusive(bill.billing_period_start, bill.billing_period_end)
    bill.avg_daily_kwh = avg_daily_kwh(bill.total_kwh, days)
    bill.avg_cost_per_kwh = avg_cost_per_kwh(bill.energy_charges_cents, bill.total_kwh)
    bill.effective_total_cost_per_kwh = effective_total_cost_per_kwh(
        bill.total_amount_cents, bill.total_kwh
    )
    return bill


def check_period(bill: Bill) -> list[str]:
    """Cross-field validation warnings (empty list when consistent)."""
    warnings: list[str] = []
    if bill.billing_period_start and bill.billing_period_end:
        if bill.billing_period_end < bill.billing_period_start:
            warnings.append("Billing period end is before its start.")
    if (
        bill.previous_reading is not None
        and bill.current_reading is not None
        and bill.total_kwh is not None
    ):
        delta = bill.current_reading - bill.previous_reading
        if delta < 0:
            warnings.append("Current meter reading is lower than the previous one.")
        elif abs(delta - bill.total_kwh) > max(2.0, bill.total_kwh * 0.05):
            warnings.append(
                f"Meter reading delta ({delta:.0f} kWh) does not match "
                f"the billed consumption ({bill.total_kwh:.0f} kWh)."
            )
    components = [c for c in (bill.energy_charges_cents, bill.fixed_charges_cents, bill.taxes_and_fees_cents) if c is not None]
    if bill.total_amount_cents is not None and len(components) == 3:
        s = sum(components)
        if abs(s - bill.total_amount_cents) > 150:  # > 1.50 EUR off
            warnings.append(
                f"Components sum to {s / 100:.2f} but total is {bill.total_amount_cents / 100:.2f}."
            )
    return warnings
