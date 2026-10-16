"""Repositories: the only place that knows about SQLAlchemy rows.

Everything here converts to/from :mod:`wattly.core.models` dataclasses,
so services and the web layer never touch ORM objects.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from wattly.core.models import Bill, DocumentInfo, ParsingLogEntry, TimeBand
from wattly.database import models as m


# --------------------------------------------------------------------- #
# Mapping helpers
# --------------------------------------------------------------------- #
def _band_to_domain(row: m.TimeBandRow) -> TimeBand:
    return TimeBand(label=row.label, kwh=row.kwh, amount_cents=row.amount_cents)


def bill_to_domain(row: m.BillRow) -> Bill:
    return Bill(
        id=row.id,
        document_id=row.document_id,
        provider_name=row.provider_name or "",
        account_number=row.account_number,
        pod_identifier=row.pod_identifier,
        issue_date=row.issue_date,
        billing_period_start=row.billing_period_start,
        billing_period_end=row.billing_period_end,
        total_amount_cents=row.total_amount_cents,
        currency=row.currency or "EUR",
        total_kwh=row.total_kwh,
        avg_daily_kwh=row.avg_daily_kwh,
        avg_cost_per_kwh=row.avg_cost_per_kwh,
        effective_total_cost_per_kwh=row.effective_total_cost_per_kwh,
        fixed_charges_cents=row.fixed_charges_cents,
        energy_charges_cents=row.energy_charges_cents,
        taxes_and_fees_cents=row.taxes_and_fees_cents,
        previous_reading=row.previous_reading,
        current_reading=row.current_reading,
        reading_start_date=row.reading_start_date,
        reading_end_date=row.reading_end_date,
        tariff_type=row.tariff_type,
        parse_method=row.parse_method or "manual",
        parse_confidence=row.parse_confidence,
        field_sources=dict(row.field_sources or {}),
        notes=row.notes or "",
        status=row.status or "confirmed",
        time_bands=[_band_to_domain(b) for b in row.bands],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def bill_to_row(bill: Bill, row: m.BillRow | None = None) -> m.BillRow:
    row = row or m.BillRow()
    row.document_id = bill.document_id
    row.provider_name = bill.provider_name
    row.account_number = bill.account_number
    row.pod_identifier = bill.pod_identifier
    row.issue_date = bill.issue_date
    row.billing_period_start = bill.billing_period_start
    row.billing_period_end = bill.billing_period_end
    row.total_amount_cents = bill.total_amount_cents
    row.currency = bill.currency
    row.total_kwh = bill.total_kwh
    row.avg_daily_kwh = bill.avg_daily_kwh
    row.avg_cost_per_kwh = bill.avg_cost_per_kwh
    row.effective_total_cost_per_kwh = bill.effective_total_cost_per_kwh
    row.fixed_charges_cents = bill.fixed_charges_cents
    row.energy_charges_cents = bill.energy_charges_cents
    row.taxes_and_fees_cents = bill.taxes_and_fees_cents
    row.previous_reading = bill.previous_reading
    row.current_reading = bill.current_reading
    row.reading_start_date = bill.reading_start_date
    row.reading_end_date = bill.reading_end_date
    row.tariff_type = bill.tariff_type
    row.parse_method = bill.parse_method
    row.parse_confidence = bill.parse_confidence
    row.field_sources = dict(bill.field_sources)
    row.notes = bill.notes
    row.status = bill.status
    return row


def _sync_bands(row: m.BillRow, bands: Iterable[TimeBand]) -> None:
    row.bands = [
        m.TimeBandRow(label=b.label, kwh=b.kwh, amount_cents=b.amount_cents)
        for b in bands
        if b.label
    ]


# --------------------------------------------------------------------- #
class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str, default: Any = None) -> Any:
        row = self.session.get(m.SettingRow, key)
        return row.value if row else default

    def set(self, key: str, value: Any) -> None:
        row = self.session.get(m.SettingRow, key)
        if row is None:
            row = m.SettingRow(key=key)
            self.session.add(row)
        row.value = value if isinstance(value, str) else str(value)

    def all(self) -> dict[str, str]:
        return {r.key: r.value for r in self.session.scalars(select(m.SettingRow))}


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, info: DocumentInfo) -> DocumentInfo:
        row = m.DocumentRow(
            sha256=info.sha256,
            original_filename=info.original_filename,
            stored_path=info.stored_path,
            mime_type=info.mime_type,
            page_count=info.page_count,
            ocr_used=info.ocr_used,
        )
        self.session.add(row)
        self.session.flush()
        info.id = row.id
        return info

    def by_sha256(self, sha256: str) -> DocumentInfo | None:
        row = self.session.scalars(
            select(m.DocumentRow).where(m.DocumentRow.sha256 == sha256)
        ).first()
        return self._to_domain(row) if row else None

    def get(self, doc_id: int) -> DocumentInfo | None:
        row = self.session.get(m.DocumentRow, doc_id)
        return self._to_domain(row) if row else None

    def mark_ocr(self, doc_id: int, ocr_used: bool, page_count: int | None) -> None:
        row = self.session.get(m.DocumentRow, doc_id)
        if row:
            row.ocr_used = ocr_used
            if page_count:
                row.page_count = page_count

    def recent(self, limit: int = 10) -> list[DocumentInfo]:
        rows = self.session.scalars(
            select(m.DocumentRow).order_by(m.DocumentRow.id.desc()).limit(limit)
        )
        return [self._to_domain(r) for r in rows]

    def unlinked(self) -> list[DocumentInfo]:
        """Uploaded documents that are not linked to any bill yet."""
        q = (
            select(m.DocumentRow)
            .outerjoin(m.BillRow, m.BillRow.document_id == m.DocumentRow.id)
            .where(m.BillRow.id.is_(None))
            .order_by(m.DocumentRow.id.asc())
        )
        return [self._to_domain(r) for r in self.session.scalars(q).unique()]

    @staticmethod
    def _to_domain(row: m.DocumentRow) -> DocumentInfo:
        return DocumentInfo(
            id=row.id, sha256=row.sha256, original_filename=row.original_filename,
            stored_path=row.stored_path, mime_type=row.mime_type,
            page_count=row.page_count, ocr_used=bool(row.ocr_used),
            uploaded_at=row.uploaded_at,
        )


class BillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, bill: Bill) -> Bill:
        """Insert or update (when bill.id is set)."""
        if bill.id:
            row = self.session.get(m.BillRow, bill.id, options=[selectinload(m.BillRow.bands)])
            if row is None:
                raise LookupError(f"Bill {bill.id} not found")
            bill_to_row(bill, row)
            _sync_bands(row, bill.time_bands)
        else:
            row = bill_to_row(bill)
            _sync_bands(row, bill.time_bands)
            self.session.add(row)
        self.session.flush()
        saved = self.get(row.id)
        assert saved is not None
        return saved

    def get(self, bill_id: int) -> Bill | None:
        row = self.session.scalars(
            select(m.BillRow).where(m.BillRow.id == bill_id).options(selectinload(m.BillRow.bands))
        ).first()
        return bill_to_domain(row) if row else None

    def list(
        self,
        provider: str | None = None,
        year: int | None = None,
        month: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        min_cost_cents: int | None = None,
        max_cost_cents: int | None = None,
        min_kwh: float | None = None,
        max_kwh: float | None = None,
        search: str | None = None,
        status: str = "confirmed",
    ) -> list[Bill]:
        q = select(m.BillRow).options(selectinload(m.BillRow.bands))
        conds = []
        key = m.BillRow.billing_period_start
        if status != "all":
            conds.append(m.BillRow.status == status)
        if provider:
            conds.append(m.BillRow.provider_name.ilike(f"%{provider}%"))
        if year:
            conds.append(m.BillRow.billing_period_start.between(date(year, 1, 1), date(year, 12, 31)))
        if month and year:
            import calendar

            last = calendar.monthrange(year, month)[1]
            conds.append(m.BillRow.billing_period_start.between(date(year, month, 1), date(year, month, last)))
        if date_from:
            conds.append(key >= date_from)
        if date_to:
            conds.append(key <= date_to)
        if min_cost_cents is not None:
            conds.append(m.BillRow.total_amount_cents >= min_cost_cents)
        if max_cost_cents is not None:
            conds.append(m.BillRow.total_amount_cents <= max_cost_cents)
        if min_kwh is not None:
            conds.append(m.BillRow.total_kwh >= min_kwh)
        if max_kwh is not None:
            conds.append(m.BillRow.total_kwh <= max_kwh)
        if search:
            like = f"%{search}%"
            conds.append(
                and_(
                    m.BillRow.provider_name.ilike(like)
                    | m.BillRow.pod_identifier.ilike(like)  # type: ignore[operator]
                    | m.BillRow.account_number.ilike(like)  # type: ignore[operator]
                    | m.BillRow.notes.ilike(like)  # type: ignore[operator]
                )
            )
        if conds:
            q = q.where(and_(*conds))
        q = q.order_by(m.BillRow.billing_period_start.asc())
        return [bill_to_domain(r) for r in self.session.scalars(q)]

    def all_confirmed(self) -> list[Bill]:
        return self.list(status="confirmed")

    def find_duplicates(
        self, provider: str, period_start: date | None, period_end: date | None, exclude_id: int | None = None
    ) -> list[Bill]:
        """Same provider and (roughly) same billing period → probable duplicate."""
        q = select(m.BillRow).options(selectinload(m.BillRow.bands)).where(
            m.BillRow.provider_name.ilike(f"%{provider}%")
        )
        if period_start:
            q = q.where(m.BillRow.billing_period_start == period_start)
        if period_end:
            q = q.where(m.BillRow.billing_period_end == period_end)
        rows = self.session.scalars(q)
        return [bill_to_domain(r) for r in rows if r.id != exclude_id]

    def delete(self, bill_id: int) -> bool:
        row = self.session.get(m.BillRow, bill_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def count(self) -> int:
        return len(self.session.scalars(select(m.BillRow.id)).all())

    def by_document(self, document_id: int) -> list[Bill]:
        rows = self.session.scalars(
            select(m.BillRow)
            .where(m.BillRow.document_id == document_id)
            .options(selectinload(m.BillRow.bands))
            .order_by(m.BillRow.id.desc())
        )
        return [bill_to_domain(r) for r in rows]


class LogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        step: str,
        status: str,
        message: str = "",
        confidence: float | None = None,
        excerpt: str | None = None,
        document_id: int | None = None,
        bill_id: int | None = None,
    ) -> None:
        self.session.add(
            m.ParsingLogRow(
                step=step, status=status, message=message,
                confidence=confidence, excerpt=excerpt,
                document_id=document_id, bill_id=bill_id,
            )
        )

    def for_bill(self, bill_id: int) -> list[ParsingLogEntry]:
        rows = self.session.scalars(
            select(m.ParsingLogRow)
            .where(m.ParsingLogRow.bill_id == bill_id)
            .order_by(m.ParsingLogRow.id.asc())
        )
        return [self._to_domain(r) for r in rows]

    def for_document(self, document_id: int) -> list[ParsingLogEntry]:
        rows = self.session.scalars(
            select(m.ParsingLogRow)
            .where(m.ParsingLogRow.document_id == document_id)
            .order_by(m.ParsingLogRow.id.asc())
        )
        return [self._to_domain(r) for r in rows]

    def recent_issues(self, limit: int = 5) -> list[ParsingLogEntry]:
        rows = self.session.scalars(
            select(m.ParsingLogRow)
            .where(m.ParsingLogRow.status.in_(["warn", "error"]))
            .order_by(m.ParsingLogRow.id.desc())
            .limit(limit)
        )
        return [self._to_domain(r) for r in rows]

    @staticmethod
    def _to_domain(row: m.ParsingLogRow) -> ParsingLogEntry:
        return ParsingLogEntry(
            id=row.id, document_id=row.document_id, bill_id=row.bill_id,
            step=row.step, status=row.status, confidence=row.confidence,
            message=row.message or "", excerpt=row.excerpt,
            created_at=row.created_at,
        )
