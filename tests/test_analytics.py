from datetime import date

from wattly.core import analytics
from wattly.core.models import Bill, TimeBand


def _bill(year, month, kwh, cents, days=None, bands=None):
    import calendar

    last = calendar.monthrange(year, month)[1]
    return Bill(
        provider_name="Test",
        billing_period_start=date(year, month, 1),
        billing_period_end=date(year, month, last),
        total_kwh=kwh, total_amount_cents=cents,
        time_bands=bands or [],
    )


def _series():
    # 8 flat months + 1 spike (August) → anomaly detection has material
    bills = [_bill(2026, m, 300, 9000) for m in range(1, 8)]
    bills.append(_bill(2026, 8, 900, 27000,
                       bands=[TimeBand("F1", 400, 6000), TimeBand("F2", 300, 4500),
                              TimeBand("F3", 200, 3000)]))
    return bills


class TestReport:
    def test_totals_and_extremes(self):
        rep = analytics.build_report(_series())
        assert rep.bill_count == 8
        assert rep.total_kwh == 8 * 300 + 600
        assert rep.highest_kwh.kwh == 900
        assert rep.lowest_kwh.kwh == 300
        assert rep.highest_cost.amount_cents == 27000
        # 90000 cents total (= €900), 3000 kWh → €0.30/kWh
        assert round(rep.effective_cost_per_kwh, 4) == 0.3

    def test_rolling_average_aligned_with_series(self):
        rep = analytics.build_report(_series())
        assert len(rep.rolling_avg_kwh) == len(rep.series)
        assert rep.rolling_avg_kwh[-1] == round((300 + 300 + 900) / 3, 2)

    def test_anomaly_flagged(self):
        rep = analytics.build_report(_series())
        assert len(rep.anomalies) == 1
        assert rep.anomalies[0].kind == "high"
        assert "Aug" in rep.anomalies[0].label or "ago" in rep.anomalies[0].label.lower()

    def test_no_anomalies_with_flat_series(self):
        bills = [_bill(2026, m, 300 + (m % 2) * 5, 9000) for m in range(1, 9)]
        rep = analytics.build_report(bills)
        assert rep.anomalies == []

    def test_band_aggregation(self):
        rep = analytics.build_report(_series())
        assert rep.band_labels == ["F1", "F2", "F3"]
        assert rep.band_kwh["F1"] == 400.0
        assert rep.band_cents["F2"] == 4500

    def test_year_over_year(self):
        bills = [_bill(2025, m, 300, 9000) for m in range(1, 13)]
        bills += [_bill(2026, m, 330, 9900) for m in range(1, 13)]
        rep = analytics.build_report(bills)
        assert len(rep.yoy) == 2
        assert rep.yoy[1]["kwh_delta_pct"] == 10.0
        assert rep.yoy[1]["cost_delta_pct"] == 10.0
        assert "partial" not in rep.yoy[1] or rep.yoy[1]["partial"] is False

    def test_partial_year_has_no_yoy_delta(self):
        bills = [_bill(2025, m, 300, 9000) for m in range(1, 13)]
        bills += [_bill(2026, m, 330, 9900) for m in range(1, 7)]
        rep = analytics.build_report(bills)
        assert rep.yoy[1]["partial"] is True
        assert "kwh_delta_pct" not in rep.yoy[1]

    def test_empty_report(self):
        rep = analytics.build_report([])
        assert rep.bill_count == 0
        assert rep.series == []
        assert rep.highest_kwh is None


class TestToPoints:
    def test_skips_incomplete_bills(self):
        bills = [_bill(2026, 1, 300, 9000), Bill(provider_name="X")]
        points = analytics.to_points(bills)
        assert len(points) == 1
        assert points[0].daily_kwh > 0
