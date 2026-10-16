"""Octopus Energy Italia parser.

Targets Octopus' "BOLLETTA LUCE" layout: "Questo mese dovrai pagare" total,
the "Scontrino dell'energia" component rows (Quota per consumi / Quota fissa
/ Quota potenza / Accise e IVA) and the PERIODO DI RIFERIMENTO line.
"""

from __future__ import annotations

import re

from wattly.parsing import extractor as ex
from wattly.parsing.normalization import parse_date, parse_number
from wattly.parsing.pdf_reader import ParsedDocument
from wattly.parsing.provider_parsers.base import (
    ExtractedValue,
    ExtractionOutcome,
    ProviderParser,
    validate_outcome,
)


class OctopusParser(ProviderParser):
    name = "octopus"

    def fingerprint(self, doc: ParsedDocument) -> float:
        head = doc.full_text[:2500].lower()
        if "octopus energy" in head and "bolletta luce" in head:
            return 0.95
        return 0.0

    def parse(self, doc: ParsedDocument) -> ExtractionOutcome:
        text = doc.full_text
        out = ExtractionOutcome()
        f = out.fields

        self._provider(text, f)
        self._account(text, f)
        self._pod(text, f)
        self._issue_date(text, f)
        self._period(text, f)
        self._kwh(text, f)
        self._total(text, f)
        self._components(text, f)
        self._tariff(text, f)

        validate_outcome(out)
        return out

    # ------------------------------------------------------------------ #
    def _provider(self, text: str, f: dict) -> None:
        m = re.search(r"^(Octopus Energy Italia.*)$", text, re.MULTILINE | re.IGNORECASE)
        if m:
            f["provider_name"] = ExtractedValue(m.group(1).strip(), 0.95, "header line")

    def _account(self, text: str, f: dict) -> None:
        m = re.search(r"Codice Fornitura:\s*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if m:
            f["account_number"] = ExtractedValue(m.group(1), 0.9, "Codice Fornitura")

    def _pod(self, text: str, f: dict) -> None:
        m = re.search(r"\bIT[0-9A-Z]{12}\b", text.upper())
        if m:
            f["pod_identifier"] = ExtractedValue(m.group(0), 0.9, "POD pattern")

    def _issue_date(self, text: str, f: dict) -> None:
        m = re.search(r"DATA FATTURA:\s*(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if m:
            d = parse_date(m.group(1))
            if d:
                f["issue_date"] = ExtractedValue(d, 0.95, "DATA FATTURA")

    def _period(self, text: str, f: dict) -> None:
        m = re.search(
            r"PERIODO DI RIFERIMENTO:\s*dal\s*(\d{1,2}[./]\d{1,2}[./]\d{4})"
            r"\s+al\s*(\d{1,2}[./]\d{1,2}[./]\d{4})",
            text, re.IGNORECASE,
        )
        if m:
            start, end = parse_date(m.group(1)), parse_date(m.group(2))
            if start and end:
                f["billing_period_start"] = ExtractedValue(start, 0.95, "PERIODO DI RIFERIMENTO")
                f["billing_period_end"] = ExtractedValue(end, 0.95, "PERIODO DI RIFERIMENTO")

    def _kwh(self, text: str, f: dict) -> None:
        m = re.search(r"CONSUMO FATTURATO:\s*([\d.,]+)\s*kWh", text, re.IGNORECASE)
        if m:
            v = parse_number(m.group(1))
            if v is not None:
                f["total_kwh"] = ExtractedValue(v, 0.95, "CONSUMO FATTURATO")

    def _total(self, text: str, f: dict) -> None:
        cents = ex.amount_after_label(text, r"TOTALE\s+BOLLETTA", min_cents=100)
        if cents is None:
            cents = ex.amount_after_label(text, r"Questo mese dovrai pagare", min_cents=100)
        if cents:
            f["total_amount_cents"] = ExtractedValue(cents, 0.95, "total row")

    def _components(self, text: str, f: dict) -> None:
        energy = ex.amount_after_label(text, r"^Quota per consumi\s*$",
                                       min_cents=50, euro_line="last",
                                       case_sensitive=True)
        if energy:
            f["energy_charges_cents"] = ExtractedValue(energy, 0.85, "scontrino")
        fixed = 0
        found = False
        for anchor in (r"^Quota fissa\s*$", r"^Quota potenza\s*$"):
            cents = ex.amount_after_label(text, anchor, min_cents=50,
                                          euro_line="last", case_sensitive=True)
            if cents:
                fixed += cents
                found = True
        if found:
            f["fixed_charges_cents"] = ExtractedValue(fixed, 0.8, "scontrino rows")
        taxes = ex.amount_after_label(text, r"^Accise e IVA\s*$", min_cents=10,
                                      case_sensitive=True)
        if taxes:
            f["taxes_and_fees_cents"] = ExtractedValue(taxes, 0.85, "scontrino")

    def _tariff(self, text: str, f: dict) -> None:
        m = re.search(r"NOME OFFERTA:\s*(.+)", text, re.IGNORECASE)
        if m:
            f["tariff_type"] = ExtractedValue(m.group(1).strip(), 0.9, "NOME OFFERTA")
