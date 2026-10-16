from datetime import date

from wattly.parsing.normalization import (
    normalize_band_label,
    parse_amount_to_cents,
    parse_date,
    parse_number,
)


class TestParseDate:
    def test_iso(self):
        assert parse_date("2026-09-05") == date(2026, 9, 5)
        assert parse_date("05/09/2026") == date(2026, 9, 5)

    def test_italian_month_name(self):
        assert parse_date("15 luglio 2026") == date(2026, 7, 15)
        assert parse_date("luglio 2026") == date(2026, 7, 1)

    def test_english_month_name(self):
        assert parse_date("July 15, 2026") == date(2026, 7, 15)
        assert parse_date("15 March 2025") == date(2025, 3, 15)

    def test_garbage(self):
        assert parse_date("not a date") is None
        assert parse_date(None) is None
        assert parse_date("45/13/2026") is None


class TestParseNumber:
    def test_italian_format(self):
        assert parse_number("1.234,56", "it") == 1234.56
        assert parse_number("89,77", "it") == 89.77
        assert parse_number("347,0", "it") == 347.0

    def test_international_format(self):
        assert parse_number("1,234.56", "en") == 1234.56
        assert parse_number("89.77", "en") == 89.77

    def test_ambiguous_thousands(self):
        assert parse_number("1,234", "it") == 1.234
        assert parse_number("1,234", "en") == 1234

    def test_euro_symbol_and_spaces(self):
        assert parse_number("€ 1.234,56", "it") == 1234.56
        assert parse_number("1 234,56", "it") == 1234.56

    def test_garbage(self):
        assert parse_number("") is None
        assert parse_number("abc") is None


class TestAmountToCents:
    def test_basic(self):
        assert parse_amount_to_cents("89,77", "it") == 8977
        assert parse_amount_to_cents("1.234,56", "it") == 123456
        assert parse_amount_to_cents("0.05", "en") == 5

    def test_rounding(self):
        assert parse_amount_to_cents("10,995", "it") == 1100  # half-up
        assert parse_amount_to_cents("10,994", "it") == 1099


class TestBandLabels:
    def test_canonicalization(self):
        assert normalize_band_label("F1") == "F1"
        assert normalize_band_label("fascia 2") == "F2"
        assert normalize_band_label("Fascia 3") == "F3"
        assert normalize_band_label("monoraria") == "Mono"
        assert normalize_band_label("peak") == "F1"
        assert normalize_band_label("random") is None
