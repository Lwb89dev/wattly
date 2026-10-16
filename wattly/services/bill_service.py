"""Bill lifecycle: create, update, filter, delete, duplicate checks."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from wattly.core import calculators
from wattly.core.models import Bill
from wattly.database.repositories import BillRepository, LogRepository


class BillService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = BillRepository(session)
        self.logs = LogRepository(session)

    def create(self, bill: Bill) -> Bill:
        calculators.recompute_derived(bill)
        bill.status = bill.status or "confirmed"
        saved = self.repo.save(bill)
        self.session.commit()
        return saved

    def update(self, bill: Bill) -> Bill:
        calculators.recompute_derived(bill)
        saved = self.repo.save(bill)
        self.logs.add("edit", "ok", "Bill updated manually.", bill_id=bill.id)
        self.session.commit()
        return saved

    def get(self, bill_id: int) -> Bill | None:
        return self.repo.get(bill_id)

    def delete(self, bill_id: int) -> bool:
        ok = self.repo.delete(bill_id)
        if ok:
            self.session.commit()
        return ok

    def list(self, **filters) -> list[Bill]:
        return self.repo.list(**filters)

    def all_confirmed(self) -> list[Bill]:
        return self.repo.all_confirmed()

    def providers(self) -> list[str]:
        seen: list[str] = []
        for b in self.repo.list(status="confirmed"):
            name = (b.provider_name or "").strip()
            if name and name not in seen:
                seen.append(name)
        return sorted(seen, key=str.lower)

    def years(self) -> list[int]:
        ys = {
            (b.billing_period_start or b.issue_date).year
            for b in self.repo.list(status="confirmed")
            if b.billing_period_start or b.issue_date
        }
        return sorted(ys)

    def duplicate_warnings(self, bill: Bill) -> list[Bill]:
        if not bill.provider_name:
            return []
        return self.repo.find_duplicates(
            bill.provider_name, bill.billing_period_start, bill.billing_period_end,
            exclude_id=bill.id,
        )

    def validation_warnings(self, bill: Bill) -> list[str]:
        return calculators.check_period(bill)

    def get_period_range(self) -> tuple[date | None, date | None]:
        bills = self.repo.list(status="confirmed")
        starts = [b.billing_period_start for b in bills if b.billing_period_start]
        ends = [b.billing_period_end for b in bills if b.billing_period_end]
        return (min(starts) if starts else None, max(ends) if ends else None)
