from datetime import date

from wattly.core import calculators
from wattly.core.models import Bill


def _bill(kwh=300.0, total=9000, days=(date(2026, 8, 1), date(2026, 8, 31)),
          energy=5000, fixed=1200, taxes=2800, prev=1000.0, curr=1300.0):
    return Bill(
        provider_name="Test Energy",
        billing_period_start=days[0], billing_period_end=days[1],
        total_amount_cents=total, total_kwh=kwh,
        energy_charges_cents=energy, fixed_charges_cents=fixed, taxes_and_fees_cents=taxes,
        previous_reading=prev, current_reading=curr,
    )


class TestDerived:
    def test_recompute_derived(self):
        bill = _bill()
        calculators.recompute_derived(bill)
        assert bill.avg_daily_kwh == round(300.0 / 31, 4)
        assert bill.avg_cost_per_kwh == round(5000 / 100 / 300.0, 6)
        assert bill.effective_total_cost_per_kwh == round(9000 / 100 / 300.0, 6)

    def test_missing_components(self):
        bill = Bill(total_kwh=100)
        calculators.recompute_derived(bill)
        assert bill.avg_cost_per_kwh is None
        assert bill.effective_total_cost_per_kwh is None


class TestValidation:
    def test_consistent_bill_has_no_warnings(self):
        assert calculators.check_period(_bill()) == []

    def test_inverted_period(self):
        bill = _bill(days=(date(2026, 8, 31), date(2026, 8, 1)))
        assert any("before its start" in w for w in calculators.check_period(bill))

    def test_reading_delta_mismatch(self):
        bill = _bill(curr=2000.0)  # delta 1000 != 300 kWh
        assert any("does not match" in w for w in calculators.check_period(bill))

    def test_negative_reading_delta(self):
        bill = _bill(curr=500.0)
        assert any("lower than the previous" in w for w in calculators.check_period(bill))

    def test_component_sum_mismatch(self):
        bill = _bill(energy=9000)  # sum = 13000 != 9000
        assert any("sum" in w.lower() for w in calculators.check_period(bill))
