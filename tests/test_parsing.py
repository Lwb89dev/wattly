"""End-to-end parsing tests against generated sample bills (ground truth known)."""

from datetime import date

import pytest

from wattly.parsing import ImportPipeline
from wattly.parsing.provider_parsers import PARSERS, detect_parser
from wattly.parsing.provider_parsers.generic import GenericProviderParser
from wattly.parsing.pdf_reader import extract_text_pdf, text_coverage


@pytest.fixture()
def results(sample_pdfs):
    pipeline = ImportPipeline(ocr_enabled=False)
    out = {}
    for path in sample_pdfs:
        out[path.name] = pipeline.parse(path)
    return out


class TestTextSamples:
    def test_coverage_is_high(self, sample_pdfs):
        for path in sample_pdfs:
            if "scanned" in path.name:
                continue
            assert text_coverage(path) >= 0.9

    def test_luceverde_fields(self, results):
        r = results["wattly_bill_luceverde_2026-08.pdf"]
        assert r.error is None
        f = r.fields
        assert f["provider_name"] == "LUCEVERDE ENERGIA S.P.A."
        assert f["total_amount_cents"] == 9188
        assert f["total_kwh"] == 347.0
        assert f["pod_identifier"] == "IT001E12345678"
        assert f["account_number"] == "40219376"
        assert f["issue_date"] == date(2026, 9, 5)
        assert f["billing_period_start"] == date(2026, 8, 1)
        assert f["billing_period_end"] == date(2026, 8, 31)
        assert f["energy_charges_cents"] == 5017
        assert f["fixed_charges_cents"] == 1184
        assert f["taxes_and_fees_cents"] == 2987
        assert f["previous_reading"] == 12450.0
        assert f["current_reading"] == 12797.0
        assert r.parse_method == "text"
        assert r.confidence >= 0.75

    def test_luceverde_bands(self, results):
        r = results["wattly_bill_luceverde_2026-08.pdf"]
        bands = {b.label: b.kwh for b in r.bands}
        assert bands == {"F1": 132.0, "F2": 114.0, "F3": 101.0}
        # bands sum equals total → no band-sum warning
        assert not any("bands sum" in w.lower() for w in r.warnings)

    def test_elettra_fields(self, results):
        r = results["wattly_bill_elettra_2026-09.pdf"]
        assert r.error is None
        f = r.fields
        assert f["provider_name"] == "ELETTRA S.R.L."
        assert f["total_amount_cents"] == 8457
        assert f["total_kwh"] == 312.0
        assert f["billing_period_start"] == date(2026, 9, 1)
        assert f["billing_period_end"] == date(2026, 9, 30)
        assert f["issue_date"] == date(2026, 10, 4)
        assert f["account_number"] == "88-451290"
        assert f["tariff_type"] == "Monoraria"
        assert f["energy_charges_cents"] == 4649
        assert f["fixed_charges_cents"] == 1090
        assert f["taxes_and_fees_cents"] == 2718

    def test_elettra_no_band_warning_for_mono(self, results):
        r = results["wattly_bill_elettra_2026-09.pdf"]
        assert r.bands == []


class TestScannedSample:
    def test_scanned_falls_back_gracefully(self, results):
        # tesseract is not installed in this environment: the pipeline must
        # degrade to raw (empty) text with an explicit log, never crash.
        r = results["wattly_bill_luceverde_2026-08_scanned.pdf"]
        assert r.error is None
        assert r.parse_method in {"text-partial"}
        steps = [l["step"] for l in r.logs]
        assert "ocr" in steps
        ocr_log = next(l for l in r.logs if l["step"] == "ocr")
        assert ocr_log["status"] in {"unavailable", "skipped", "ok", "warn"}
        assert r.confidence < 0.75 or not r.fields


class TestProviderDetection:
    def test_generic_is_default(self, sample_pdfs):
        doc = extract_text_pdf(sample_pdfs[0])
        parser = detect_parser(doc, PARSERS)
        assert isinstance(parser, GenericProviderParser)
        assert parser.fingerprint(doc) == 0.0
