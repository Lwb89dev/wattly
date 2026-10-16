"""End-to-end web tests: full import → review → confirm → analytics → export."""

from __future__ import annotations

LUCEVERDE_FORM = {
    "provider_name": "LUCEVERDE ENERGIA S.P.A.",
    "account_number": "40219376",
    "pod_identifier": "IT001E12345678",
    "issue_date": "2026-09-05",
    "billing_period_start": "2026-08-01",
    "billing_period_end": "2026-08-31",
    "tariff_type": "Trifaria F1/F2/F3",
    "currency": "EUR",
    "total_amount": "91,88",
    "total_kwh": "347",
    "energy_charges": "50,17",
    "fixed_charges": "11,84",
    "taxes_and_fees": "29,87",
    "previous_reading": "12450",
    "current_reading": "12797",
    "reading_start_date": "2026-08-01",
    "reading_end_date": "2026-08-31",
    "band_label": ["F1", "F2", "F3"],
    "band_kwh": ["132", "114", "101"],
    "band_amount": ["19,93", "16,30", "13,94"],
    "notes": "test import",
}


class TestPages:
    def test_dashboard_empty(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Understand your energy" in r.data

    def test_dashboard_with_demo_data(self, client):
        client.post("/settings/demo")
        r = client.get("/")
        assert r.status_code == 200
        assert b"Consumption" in r.data
        assert b"trend" in r.data.lower()

    def test_analytics_page(self, client):
        client.post("/settings/demo")
        r = client.get("/analytics")
        assert r.status_code == 200
        assert b"Effective" in r.data
        assert b"Year over year" in r.data

    def test_compare_page_defaults(self, client):
        client.post("/settings/demo")
        r = client.get("/compare")
        assert r.status_code == 200
        assert b"Period A" in r.data

    def test_compare_specific(self, client):
        client.post("/settings/demo")
        r = client.get("/compare?kind_a=month&value_a=2026-01&kind_b=month&value_b=2026-08")
        assert r.status_code == 200
        assert "Δ".encode() in r.data or b"Delta" in r.data

    def test_compare_seasons(self, client):
        client.post("/settings/demo")
        r = client.get("/compare?kind_a=season&value_a=winter&kind_b=season&value_b=summer")
        assert r.status_code == 200


class TestManualEntry:
    def test_create_and_detail(self, client):
        r = client.post("/bills/new", data=LUCEVERDE_FORM, follow_redirects=False)
        assert r.status_code == 302
        detail = client.get(r.headers["Location"])
        assert detail.status_code == 200
        assert "91,88".encode("utf-8") in detail.data
        assert b"Extraction audit" not in detail.data  # manual bill: no parse logs

    def test_validation_errors(self, client):
        bad = dict(LUCEVERDE_FORM, total_amount="abc", billing_period_start="")
        r = client.post("/bills/new", data=bad)
        assert r.status_code == 422
        assert b"required" in r.data or b"Cannot read" in r.data

    def test_edit_and_delete(self, client):
        r = client.post("/bills/new", data=LUCEVERDE_FORM)
        bill_id = r.headers["Location"].rstrip("/").split("/")[-1]
        updated = dict(LUCEVERDE_FORM, total_kwh="400", total_amount="99,90")
        r = client.post(f"/bills/{bill_id}/edit", data=updated)
        assert r.status_code == 302
        detail = client.get(f"/bills/{bill_id}")
        assert "99,90".encode() in detail.data
        r = client.post(f"/bills/{bill_id}/delete")
        assert r.status_code == 302
        assert client.get(f"/bills/{bill_id}").status_code == 404


class TestImportFlow:
    def _upload(self, client, pdf_bytes, name):
        import io

        return client.post(
            "/import/upload",
            data={"file": (io.BytesIO(pdf_bytes), name)},
            content_type="multipart/form-data",
        )

    def test_upload_review_confirm(self, client, pdf_bytes):
        raw = pdf_bytes["wattly_bill_luceverde_2026-08.pdf"]
        r = self._upload(client, raw, "bill.pdf")
        assert r.status_code == 200 and r.json["ok"]
        doc_id = r.json["doc_id"]

        # duplicate detection
        r2 = self._upload(client, raw, "bill-again.pdf")
        assert r2.json["duplicate"] is True

        review = client.get(f"/import/review/{doc_id}")
        assert review.status_code == 200
        assert b"Review extracted data" in review.data
        assert "91,88".encode() in review.data  # prefilled from extraction

        r = client.post(f"/import/review/{doc_id}", data=LUCEVERDE_FORM)
        assert r.status_code == 302
        detail = client.get(r.headers["Location"])
        assert detail.status_code == 200
        assert b"time bands" in detail.data.lower() or b"Time bands" in detail.data
        assert b"Extraction audit" in detail.data

    def test_upload_rejects_non_pdf(self, client):
        import io

        r = client.post(
            "/import/upload",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_reparse_updates_bill(self, client, pdf_bytes):
        raw = pdf_bytes["wattly_bill_luceverde_2026-08.pdf"]
        doc_id = self._upload(client, raw, "bill.pdf").json["doc_id"]
        r = client.post(f"/import/review/{doc_id}", data=LUCEVERDE_FORM)
        bill_id = r.headers["Location"].rstrip("/").split("/")[-1]

        r = client.post(f"/bills/{bill_id}/reparse")
        assert r.status_code == 302
        assert f"/import/review/{doc_id}" in r.headers["Location"]

        # confirm the re-parse (same values) → back to the same bill, no new bill
        r = client.post(f"/import/review/{doc_id}", data=dict(LUCEVERDE_FORM, bill_id=bill_id))
        assert r.status_code == 302
        assert r.headers["Location"].rstrip("/").endswith(bill_id)


class TestHistoryFilters:
    def test_filter_by_provider(self, client):
        client.post("/settings/demo")
        r = client.get("/bills?provider=luceverde")
        assert r.status_code == 200
        assert b"LuceVerde" in r.data
        assert b"Elettra" not in r.data

    def test_filter_by_year(self, client):
        client.post("/settings/demo")
        r = client.get("/bills?year=2026")
        assert r.status_code == 200


class TestExport:
    def test_bills_csv(self, client):
        client.post("/settings/demo")
        r = client.get("/export/download?what=bills&fmt=csv")
        assert r.status_code == 200
        assert "text/csv" in r.content_type
        assert r.data.startswith(b"ID,Provider")

    def test_monthly_csv(self, client):
        client.post("/settings/demo")
        r = client.get("/export/download?what=monthly&fmt=csv")
        assert r.status_code == 200
        assert b"Rolling avg" in r.data

    def test_comparison_csv_uses_last_compare(self, client):
        client.post("/settings/demo")
        r = client.get("/export/download?what=comparison&fmt=csv")
        assert r.status_code == 302  # no comparison yet → redirect with flash
        client.get("/compare")
        r = client.get("/export/download?what=comparison&fmt=csv")
        assert r.status_code == 200
        assert b"Delta" in r.data

    def test_xlsx_workbook(self, client):
        client.post("/settings/demo")
        r = client.get("/export/download?what=bills&fmt=xlsx")
        assert r.status_code == 200
        assert r.data[:2] == b"PK"  # zip magic of a real xlsx


class TestSettings:
    def test_update_settings(self, client):
        r = client.post("/settings", data={
            "currency": "USD", "locale": "en", "theme": "dark", "ocr_enabled": "1",
        })
        assert r.status_code == 302
        r = client.get("/settings")
        assert b"USD" in r.data

    def test_theme_endpoint(self, client):
        r = client.post("/settings/theme", data={"theme": "dark"})
        assert r.json["ok"] is True


class TestI18n:
    def test_catalogs_complete(self):
        from wattly.web.i18n import missing_keys

        assert missing_keys("it") == []

    def test_italian_switch(self, client):
        client.post("/settings", data={
            "language": "it", "currency": "EUR", "locale": "it", "theme": "auto",
        })
        r = client.get("/")
        assert "Cruscotto".encode("utf-8") in r.data
        assert "Fasce orarie".encode("utf-8") in r.data or "Analitiche".encode("utf-8") in r.data

    def test_back_to_english(self, client):
        client.post("/settings", data={
            "language": "it", "currency": "EUR", "locale": "it", "theme": "auto",
        })
        client.post("/settings", data={
            "language": "en", "currency": "EUR", "locale": "it", "theme": "auto",
        })
        r = client.get("/")
        assert b"Dashboard" in r.data

    def test_env_override(self, client):
        # conftest forces WATTLY_LANGUAGE=en: pages render in English
        # even though the host OS locale is Italian.
        r = client.get("/")
        assert b"local-first" in r.data


class TestAutoImport:
    def _upload(self, client, pdf_bytes, name):
        import io

        return client.post(
            "/import/upload",
            data={"file": (io.BytesIO(pdf_bytes), name)},
            content_type="multipart/form-data",
        )

    def test_bulk_import_two_bills(self, client, pdf_bytes):
        self._upload(client, pdf_bytes["wattly_bill_enel.pdf"], "enel.pdf")
        self._upload(client, pdf_bytes["wattly_bill_octopus.pdf"], "octopus.pdf")
        r = client.post("/import/auto")
        assert r.status_code == 200 and r.json["ok"]
        assert len(r.json["imported"]) == 2
        assert r.json["review"] == []
        assert r.json["duplicates"] == []
        assert r.json["pending"] == 0
        # bills are really in the archive
        hist = client.get("/bills")
        assert b"Octopus Energy" in hist.data
        assert b"Enel Energia" in hist.data

    def test_bulk_import_leaves_hard_ones_for_review(self, client, pdf_bytes):
        self._upload(client, pdf_bytes["wattly_bill_enel.pdf"], "enel.pdf")
        self._upload(client, pdf_bytes["wattly_bill_luceverde_2026-08_scanned.pdf"], "scan.pdf")
        r = client.post("/import/auto")
        assert len(r.json["imported"]) == 1
        assert len(r.json["review"]) == 1
        assert r.json["review"][0]["filename"] == "scan.pdf"

    def test_bulk_import_flags_duplicates(self, client, pdf_bytes):
        # an existing bill with the same provider+period blocks auto-import
        client.post("/bills/new", data={
            "provider_name": "Enel Energia - Mercato libero dell'energia",
            "billing_period_start": "2026-05-01",
            "billing_period_end": "2026-06-30",
            "issue_date": "2026-07-10",
            "total_amount": "141,05",
            "total_kwh": "236",
            "currency": "EUR",
        })
        self._upload(client, pdf_bytes["wattly_bill_enel.pdf"], "enel.pdf")
        r = client.post("/import/auto")
        assert len(r.json["duplicates"]) == 1
        assert len(r.json["imported"]) == 0
        # the pending doc remains for manual review
        assert r.json["pending"] == 1

    def test_import_page_shows_pending_count(self, client, pdf_bytes):
        import io

        client.post("/import/upload",
                    data={"file": (io.BytesIO(pdf_bytes["wattly_bill_enel.pdf"]), "enel.pdf")},
                    content_type="multipart/form-data")
        r = client.get("/import")
        assert b"auto-import-btn" in r.data
        assert b'"pending": 1' in r.data or b"data-pending=\"1\"" in r.data
