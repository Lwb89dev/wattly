"""Domain dataclasses shared by the whole application.

These are plain Python objects, independent of both the persistence
layer (SQLAlchemy rows are mapped to/from them in repositories) and the
parsing layer (``ParsedBillResult`` is converted into them on confirm).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class TimeBand:
    """Consumption/cost within a tariff band (F1/F2/F3 or equivalent)."""

    label: str
    kwh: float | None = None
    amount_cents: int | None = None


@dataclass
class Bill:
    id: int | None = None
    document_id: int | None = None
    provider_name: str = ""
    account_number: str | None = None
    pod_identifier: str | None = None
    issue_date: date | None = None
    billing_period_start: date | None = None
    billing_period_end: date | None = None
    total_amount_cents: int | None = None
    currency: str = "EUR"
    total_kwh: float | None = None
    avg_daily_kwh: float | None = None
    avg_cost_per_kwh: float | None = None
    effective_total_cost_per_kwh: float | None = None
    fixed_charges_cents: int | None = None
    energy_charges_cents: int | None = None
    taxes_and_fees_cents: int | None = None
    previous_reading: float | None = None
    current_reading: float | None = None
    reading_start_date: date | None = None
    reading_end_date: date | None = None
    tariff_type: str | None = None
    parse_method: str = "manual"
    parse_confidence: float | None = None
    field_sources: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    status: str = "confirmed"
    time_bands: list[TimeBand] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def period_days(self) -> int | None:
        """Inclusive number of days in the billing period."""
        if not self.billing_period_start or not self.billing_period_end:
            return None
        return (self.billing_period_end - self.billing_period_start).days + 1

    def period_key(self) -> str | None:
        """YYYY-MM key of the billing period start (used for grouping)."""
        if not self.billing_period_start:
            return None
        return self.billing_period_start.strftime("%Y-%m")


@dataclass
class DocumentInfo:
    id: int | None
    sha256: str
    original_filename: str
    stored_path: str
    mime_type: str | None
    page_count: int | None
    ocr_used: bool
    uploaded_at: datetime | None = None


@dataclass
class ParsingLogEntry:
    id: int | None
    document_id: int | None
    bill_id: int | None
    step: str
    status: str
    confidence: float | None
    message: str
    excerpt: str | None
    created_at: datetime | None = None


@dataclass
class BillPoint:
    """One time-series sample used by analytics (one per bill period)."""

    period_start: date
    period_end: date | None
    label: str  # human friendly, e.g. "Sep 2025"
    kwh: float
    amount_cents: int
    days: int
    bands: list[TimeBand] = field(default_factory=list)
    bill_id: int | None = None

    @property
    def daily_kwh(self) -> float:
        return self.kwh / self.days if self.days else 0.0

    @property
    def cost_per_kwh(self) -> float:
        euros = self.amount_cents / 100.0
        return euros / self.kwh if self.kwh else 0.0
