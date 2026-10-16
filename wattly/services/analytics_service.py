"""Read-side analytics facade used by dashboard/analytics routes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from wattly.core.analytics import AnalyticsReport, build_report
from wattly.core.models import Bill
from wattly.database.repositories import BillRepository
from wattly.services.bill_service import BillService


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = BillRepository(session)
        self.bills = BillService(session)

    def report(self) -> AnalyticsReport:
        return build_report(self.repo.all_confirmed())

    def latest(self) -> Bill | None:
        all_bills = self.repo.all_confirmed()
        with_period = [b for b in all_bills if b.billing_period_start]
        if not with_period:
            return None
        return max(with_period, key=lambda b: b.billing_period_start)

    def previous_to(self, bill: Bill | None) -> Bill | None:
        if bill is None or bill.billing_period_start is None:
            return None
        candidates = [
            b for b in self.repo.all_confirmed()
            if b.billing_period_start and b.billing_period_start < bill.billing_period_start
        ]
        return max(candidates, key=lambda b: b.billing_period_start) if candidates else None
