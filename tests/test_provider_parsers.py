"""Regression tests for the provider-specific parsers (Enel, Octopus).

The sample PDFs are layout-faithful synthetic bills (see wattly/samples.py)
with known ground truth, so no real personal documents are needed here.
"""

from datetime import date

import pytest

from wattly.parsing import ImportPipeline
from wattly.parsing.pdf_reader import extract_text_pdf
from wattly.parsing.provider_parsers import PARSERS, detect_parser
from wattly.parsing.provider_parsers.enel import EnelEnergiaParser
from wattly.parsing.provider_parsers.octopus import OctopusParser


@pytest.fixture()
def parsed(sample_pdfs):
    pipe = ImportPipeline(ocr_enabled=False)
    out = {}
    for name in ("wattly_bill_enel.pdf", "wattly_bill_enel_scontrino.pdf", "wattly_bill_octopus.pdf"):
        path = next(p for p in sample_pdfs if p.name == name)
        out[name] = pipe.parse(path)
    return out


class TestDetection:
    def test_enel_detected(self, sample_pdfs):
        doc = extract_text_pdf(next(p for p in sample_pdfs if p.name == "wattly_bill_enel.pdf"))
        assert detect_parser(doc, PARSERS).name == "enel-energia"

    def test_octopus_detected(self, sample_pdfs):
        doc = extract_text_pdf(next(p for p in sample_pdfs if p.name == "wattly_bill_octopus.pdf"))
        assert detect_parser(doc, PARSERS).name == "octopus"

    def test_generic_still_default_for_unknown(self, sample_pdfs):
        doc = extract_text_pdf(next(p for p in sample_pdfs if "luceverde_2026" in p.name))
        assert detect_parser(doc, PARSERS).name == "generic"


class TestEnelClassic:
    """2024 layout: (A)/(B) summary rows on page 1."""

    def test_fields(self, parsed):
        r = parsed["wattly_bill_enel.pdf"]
        assert r.error is None
        assert r.parser_name == "enel-energia"
        f = r.fields
        assert f["provider_name"] == "Enel Energia - Mercato libero dell'energia"
        assert f["total_amount_cents"] == 14105
        assert f["total_kwh"] == 236.0
        assert f["account_number"] == "987654321"
        assert f["pod_identifier"] == "IT012E00009988"
        assert f["issue_date"] == date(2026, 7, 10)
        assert f["billing_period_start"] == date(2026, 5, 1)
        assert f["billing_period_end"] == date(2026, 6, 30)
        assert f["energy_charges_cents"] == 6834
        assert f["fixed_charges_cents"] == 3090
        assert f["taxes_and_fees_cents"] == 2466 + 1715

    def test_bands_and_readings(self, parsed):
        r = parsed["wattly_bill_enel.pdf"]
        bands = {b.label: b.kwh for b in r.bands}
        assert bands == {"F1": 54.0, "F2": 101.0, "F3": 81.0}
        assert sum(bands.values()) == r.fields["total_kwh"]
        # readings: 9850 → 10086, delta equals billed kWh
        assert r.fields["previous_reading"] == 9850.0
        assert r.fields["current_reading"] == 10086.0
        assert r.fields["current_reading"] - r.fields["previous_reading"] == 236.0
        assert r.warnings == []

    def test_confidence(self, parsed):
        assert parsed["wattly_bill_enel.pdf"].confidence >= 0.9


class TestEnelScontrino:
    """2025+ layout: itemised scontrino, mono customer, single-column readings."""

    def test_fields(self, parsed):
        r = parsed["wattly_bill_enel_scontrino.pdf"]
        assert r.error is None
        f = r.fields
        assert f["total_amount_cents"] == 12192
        assert f["total_kwh"] == 187.0
        assert f["issue_date"] == date(2026, 5, 8)
        assert f["billing_period_start"] == date(2026, 3, 1)
        assert f["billing_period_end"] == date(2026, 4, 30)
        assert f["energy_charges_cents"] == 4103
        assert f["fixed_charges_cents"] == 4310 + 2528
        assert f["taxes_and_fees_cents"] == 1251
        assert f["tariff_type"] == "Monoraria"

    def test_components_sum_to_total(self, parsed):
        r = parsed["wattly_bill_enel_scontrino.pdf"]
        f = r.fields
        assert (f["energy_charges_cents"] + f["fixed_charges_cents"]
                + f["taxes_and_fees_cents"]) == f["total_amount_cents"]

    def test_mono_band_and_readings(self, parsed):
        r = parsed["wattly_bill_enel_scontrino.pdf"]
        bands = {b.label: b.kwh for b in r.bands}
        assert bands == {"Mono": 187.0}
        assert r.fields["previous_reading"] == 9912.0
        assert r.fields["current_reading"] == 10099.0
        assert r.warnings == []


class TestOctopus:
    def test_fields(self, parsed):
        r = parsed["wattly_bill_octopus.pdf"]
        assert r.error is None
        assert r.parser_name == "octopus"
        f = r.fields
        assert f["provider_name"] == "Octopus Energy Italia Srl, società a socio unico"
        assert f["total_amount_cents"] == 8942
        assert f["total_kwh"] == 322.0
        assert f["account_number"] == "A-TEST1234"
        assert f["pod_identifier"] == "IT012E00009988"
        assert f["issue_date"] == date(2026, 5, 6)
        assert f["billing_period_start"] == date(2026, 4, 1)
        assert f["billing_period_end"] == date(2026, 4, 30)
        assert f["energy_charges_cents"] == 6118
        assert f["fixed_charges_cents"] == 792 + 1186
        assert f["taxes_and_fees_cents"] == 846
        assert f["tariff_type"] == "Octopus Fissa 12M v200"

    def test_components_sum_to_total(self, parsed):
        r = parsed["wattly_bill_octopus.pdf"]
        f = r.fields
        assert (f["energy_charges_cents"] + f["fixed_charges_cents"]
                + f["taxes_and_fees_cents"]) == f["total_amount_cents"]
        assert r.warnings == []
