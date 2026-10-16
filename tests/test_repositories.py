from datetime import date

from wattly.core.models import Bill, TimeBand
from wattly.database.repositories import BillRepository, SettingsRepository


def _bill(provider="RepoTest", start=date(2026, 3, 1), end=date(2026, 3, 31),
          kwh=300.0, cents=9000):
    return Bill(
        provider_name=provider, billing_period_start=start, billing_period_end=end,
        total_kwh=kwh, total_amount_cents=cents,
        time_bands=[TimeBand("F1", 150, 4500), TimeBand("F2", 150, 4500)],
    )


class TestBillRepository:
    def test_roundtrip_with_bands(self, db_session):
        repo = BillRepository(db_session)
        saved = repo.save(_bill())
        db_session.commit()
        loaded = repo.get(saved.id)
        assert loaded.provider_name == "RepoTest"
        assert loaded.total_amount_cents == 9000
        assert [b.label for b in loaded.time_bands] == ["F1", "F2"]
        assert loaded.id == saved.id

    def test_update(self, db_session):
        repo = BillRepository(db_session)
        saved = repo.save(_bill())
        db_session.commit()
        saved.total_kwh = 333.0
        saved.time_bands = [TimeBand("Mono", 333.0)]
        repo.save(saved)
        db_session.commit()
        loaded = repo.get(saved.id)
        assert loaded.total_kwh == 333.0
        assert len(loaded.time_bands) == 1
        assert loaded.time_bands[0].label == "Mono"

    def test_filters(self, db_session):
        repo = BillRepository(db_session)
        repo.save(_bill(provider="Alpha", start=date(2026, 1, 1), end=date(2026, 1, 31), cents=5000))
        repo.save(_bill(provider="Beta", start=date(2026, 2, 1), end=date(2026, 2, 28), kwh=500.0, cents=15000))
        db_session.commit()

        assert len(repo.list(provider="alp")) == 1
        assert len(repo.list(year=2026, month=2)) == 1
        assert len(repo.list(min_cost_cents=10000)) == 1
        assert len(repo.list(max_kwh=400)) == 1
        assert len(repo.list(date_from=date(2026, 2, 1))) == 1
        assert len(repo.list(search="beta")) == 1
        assert len(repo.list()) == 2

    def test_duplicate_detection(self, db_session):
        repo = BillRepository(db_session)
        saved = repo.save(_bill())
        db_session.commit()
        dups = repo.find_duplicates("RepoTest", date(2026, 3, 1), date(2026, 3, 31))
        assert [d.id for d in dups] == [saved.id]
        assert repo.find_duplicates("RepoTest", date(2026, 3, 1), date(2026, 3, 31),
                                    exclude_id=saved.id) == []

    def test_delete_cascades_bands(self, db_session):
        repo = BillRepository(db_session)
        saved = repo.save(_bill())
        db_session.commit()
        assert repo.delete(saved.id) is True
        db_session.commit()
        assert repo.get(saved.id) is None
        assert BillRepository(db_session).count() == 0


class TestSettingsRepository:
    def test_set_get_all(self, db_session):
        repo = SettingsRepository(db_session)
        repo.set("theme", "dark")
        repo.set("currency", "EUR")
        db_session.commit()
        assert repo.get("theme") == "dark"
        assert repo.get("missing", "fallback") == "fallback"
        assert repo.all()["currency"] == "EUR"
