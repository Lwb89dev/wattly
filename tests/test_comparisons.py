from datetime import date

from wattly.core import comparisons
from wattly.core.models import Bill


def _bill(year, month, kwh, cents, provider="Test", day=1, end_day=None):
    import calendar

    if end_day is None:
        end_day = calendar.monthrange(year, month)[1]
    return Bill(
        provider_name=provider,
        billing_period_start=date(year, month, day),
        billing_period_end=date(year, month, end_day),
        total_kwh=kwh, total_amount_cents=cents,
    )


BILLS = [
    _bill(2026, 1, 300, 9000),
    _bill(2026, 2, 330, 9900),
    _bill(2026, 6, 500, 15000),
    _bill(2026, 7, 520, 15600),
    _bill(2026, 8, 480, 14400, provider="Other Co"),
    _bill(2025, 7, 400, 12000),
]


class TestSelect:
    def test_month(self):
        found, label = comparisons.select(BILLS, "month", "2026-02")
        assert [b.total_kwh for b in found] == [330]
        assert "Feb" in label

    def test_quarter(self):
        found, label = comparisons.select(BILLS, "quarter", "2026-Q3")
        assert {b.total_kwh for b in found} == {520, 480}
        assert label == "Q3 2026"

    def test_year(self):
        found, _ = comparisons.select(BILLS, "year", "2025")
        assert len(found) == 1

    def test_season(self):
        found, label = comparisons.select(BILLS, "season", "summer:2026")
        assert {b.total_kwh for b in found} == {500, 520, 480}

    def test_season_all_years(self):
        found, _ = comparisons.select(BILLS, "season", "summer")
        assert len(found) == 4  # Jun/Jul/Aug 2026 + Jul 2025

    def test_range(self):
        found, label = comparisons.select(BILLS, "range", "2026-01-15:2026-07-31")
        assert {b.total_kwh for b in found} == {330, 500, 520}

    def test_provider(self):
        found, _ = comparisons.select(BILLS, "provider", "other")
        assert len(found) == 1 and found[0].provider_name == "Other Co"


class TestAggregate:
    def test_day_weighted(self):
        agg = comparisons.aggregate([_bill(2026, 1, 310, 9300, day=1, end_day=31)], "Jan")
        assert agg.kwh == 310
        assert agg.daily_kwh == round(310 / 31, 3)
        assert agg.cost_per_kwh == round(93 / 310, 4)


class TestCompare:
    def test_deltas(self):
        jan = comparisons.aggregate(comparisons.select(BILLS, "month", "2026-01")[0], "Jan")
        feb = comparisons.aggregate(comparisons.select(BILLS, "month", "2026-02")[0], "Feb")
        res = comparisons.compare(jan, feb)
        assert res.kwh_delta == 30.0
        assert res.kwh_delta_pct == 10.0
        assert res.cost_delta_cents == 900
        assert res.cost_delta_pct == 10.0
        assert res.daily_kwh_delta > 0  # 30 vs 31 days, day-weighted

    def test_per_kwh_delta(self):
        a = comparisons.aggregate([_bill(2026, 1, 300, 9000)], "A")
        b = comparisons.aggregate([_bill(2026, 2, 300, 12000)], "B")
        res = comparisons.compare(a, b)
        assert res.cost_per_kwh_delta == round(0.40 - 0.30, 4)
