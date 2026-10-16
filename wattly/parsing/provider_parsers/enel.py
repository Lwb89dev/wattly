"""Enel Energia "bolletta sintetica" parser.

Targets the layout of Enel Mercato Libero synthetic bills: the page-1
summary box ("Quanto pago…", component rows marked (A)/(B)), the
"Consumo rilevato/fatturato (dal … al …)" consumption block with F1/F2/F3
or Mono values on the lines below the labels, and the "Riepilogo delle
letture" readings table (cumulative per-band meter readings).

Built against real bills; the regression coverage lives in
tests/test_parsing.py via a layout-faithful synthetic sample
(``wattly/samples.py``).
"""

from __future__ import annotations

import re

from wattly.core.models import TimeBand
from wattly.parsing import extractor as ex
from wattly.parsing.normalization import parse_date, parse_number
from wattly.parsing.pdf_reader import ParsedDocument
from wattly.parsing.provider_parsers.base import (
    ExtractedValue,
    ExtractionOutcome,
    ProviderParser,
    validate_outcome,
)

# Italian 3-letter month abbreviations used in "Periodo SET. 2024 - OTT. 2024".
_MONTH_ABBR = {
    "GEN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAG": 5, "GIU": 6,
    "LUG": 7, "AGO": 8, "SET": 9, "SEP": 9, "OTT": 10, "NOV": 11, "DIC": 12,
}


class EnelEnergiaParser(ProviderParser):
    name = "enel-energia"

    def fingerprint(self, doc: ParsedDocument) -> float:
        head = doc.full_text[:3000].lower()
        if "enel energia" in head and ("codice pod" in head or "n° cliente" in head):
            return 0.95
        return 0.0

    def parse(self, doc: ParsedDocument) -> ExtractionOutcome:
        text = doc.full_text
        out = ExtractionOutcome()
        f = out.fields

        self._provider(text, f)
        self._total(text, f)
        self._components(text, f)
        self._period(text, f)
        self._issue_date(text, f)
        self._kwh(text, f)
        self._account(text, f)
        self._pod(text, f)
        self._tariff_and_bands(text, out)
        self._readings(text, f)

        validate_outcome(out)
        return out

    # ------------------------------------------------------------------ #
    def _provider(self, text: str, f: dict) -> None:
        m = re.search(r"^Enel Energia.*$", text, re.MULTILINE | re.IGNORECASE)
        if m:
            f["provider_name"] = ExtractedValue(m.group(0).strip(), 0.95, "header line")

    def _total(self, text: str, f: dict) -> None:
        for anchor in (r"Totale\s+Bolletta", r"Quanto pago per questa bolletta",
                       r"Totale da pagare"):
            cents = ex.amount_after_label(text, anchor, min_cents=500)
            if cents:
                f["total_amount_cents"] = ExtractedValue(cents, 0.95, f"after '{anchor}'")
                return

    def _components(self, text: str, f: dict) -> None:
        # The (A)/(B) summary box only exists on page 1 — searching the whole
        # document would hit the e-invoice itemisation table ("Totale spesa
        # per il trasporto… 39,98"), which uses different row groupings.
        head = text[:4000]
        energy = ex.amount_after_label(head, r"Spesa per l'energia \(A\)")
        if energy:
            f["energy_charges_cents"] = ExtractedValue(energy, 0.9, "row (A)")
        fixed = ex.amount_after_label(
            head, r"Spesa per il trasporto dell'energia elettrica", max_lines=4
        )
        if fixed:
            f["fixed_charges_cents"] = ExtractedValue(fixed, 0.85, "transport + meter")
        taxes = 0
        found = False
        for anchor in (r"Spesa oneri di sistema \(A\)", r"Totale imposte e IVA \(B\)"):
            cents = ex.amount_after_label(head, anchor)
            if cents:
                taxes += cents
                found = True
        if found:
            f["taxes_and_fees_cents"] = ExtractedValue(taxes, 0.85, "system charges + VAT")
            return
        # 2025+ layout: itemised "Scontrino dell'energia" (same shape as
        # Octopus bills) instead of the (A)/(B) summary rows. Detail rows are
        # matched case-sensitively to skip the uppercase section headers
        # ("QUOTA FISSA E QUOTA POTENZA" also contains "Quota fissa").
        if "energy_charges_cents" not in f:
            energy = ex.amount_after_label(text, r"^Quota (?:per )?consumi\s*$",
                                           euro_line="last", case_sensitive=True)
            if energy:
                f["energy_charges_cents"] = ExtractedValue(energy, 0.85, "scontrino")
        if "fixed_charges_cents" not in f:
            fixed = 0
            ok = False
            for anchor in (r"^Quota fissa\s*$", r"^Quota potenza\s*$"):
                cents = ex.amount_after_label(text, anchor, euro_line="last",
                                              case_sensitive=True)
                if cents:
                    fixed += cents
                    ok = True
            if ok:
                f["fixed_charges_cents"] = ExtractedValue(fixed, 0.8, "scontrino rows")
        if "taxes_and_fees_cents" not in f:
            taxes = ex.amount_after_label(text, r"ACCISE E IVA", min_cents=10)
            if taxes:
                f["taxes_and_fees_cents"] = ExtractedValue(taxes, 0.85, "scontrino")

    def _period(self, text: str, f: dict) -> None:
        m = re.search(
            r"Consumo (?:rilevato|fatturato) \(dal\s*"
            r"(\d{1,2}[./]\d{1,2}[./]\d{4})\s+al\s*(\d{1,2}[./]\d{1,2}[./]\d{4})\)",
            text, re.IGNORECASE,
        )
        if m:
            start, end = parse_date(m.group(1)), parse_date(m.group(2))
            if start and end:
                f["billing_period_start"] = ExtractedValue(start, 0.95, "Consumo rilevato")
                f["billing_period_end"] = ExtractedValue(end, 0.95, "Consumo rilevato")
                return
        # Fallback: "Periodo SET. 2024 - OTT. 2024"
        m = re.search(
            r"Periodo\s+([A-Z]{3})\.?\s*(\d{4})\s*[-–]\s*([A-Z]{3})\.?\s*(\d{4})",
            text, re.IGNORECASE,
        )
        if m:
            import calendar
            from datetime import date

            m1, y1 = _MONTH_ABBR.get(m.group(1).upper()), int(m.group(2))
            m2, y2 = _MONTH_ABBR.get(m.group(3).upper()), int(m.group(4))
            if m1 and m2:
                last = calendar.monthrange(y2, m2)[1]
                f["billing_period_start"] = ExtractedValue(date(y1, m1, 1), 0.7, "month range")
                f["billing_period_end"] = ExtractedValue(date(y2, m2, last), 0.7, "month range")

    def _issue_date(self, text: str, f: dict) -> None:
        m = re.search(
            r"fattura elettronica n\.?\s*[0-9]+\s+del\s+(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE
        )
        if m:
            d = parse_date(m.group(1))
            if d:
                f["issue_date"] = ExtractedValue(d, 0.95, "fattura elettronica")

    def _kwh(self, text: str, f: dict) -> None:
        m = re.search(r"Quanto ho consumato\?\s*\n\s*([\d.,]+)\s*kWh", text, re.IGNORECASE)
        if m:
            v = parse_number(m.group(1))
            if v:
                f["total_kwh"] = ExtractedValue(v, 0.95, "summary box")
                return
        m = re.search(r"Consumo (?:del|dello) periodo\s*\n\s*([\d.,]+)\s*kWh", text, re.IGNORECASE)
        if m:
            v = parse_number(m.group(1))
            if v:
                f["total_kwh"] = ExtractedValue(v, 0.9, "Consumo del periodo")
                return
        m = re.search(r"([\d.,]+)\s*kWh\s*\n\s*consumi rilevati", text, re.IGNORECASE)
        if m:
            v = parse_number(m.group(1))
            if v:
                f["total_kwh"] = ExtractedValue(v, 0.85, "consumi rilevati")

    def _account(self, text: str, f: dict) -> None:
        m = re.search(r"N°\s*Cliente[:\s]+(\d{5,})", text, re.IGNORECASE)
        if m:
            f["account_number"] = ExtractedValue(m.group(1), 0.9, "N° Cliente")

    def _pod(self, text: str, f: dict) -> None:
        m = re.search(r"\bIT[0-9A-Z]{12}\b", text.upper())
        if m:
            f["pod_identifier"] = ExtractedValue(m.group(0), 0.9, "POD pattern")

    def _tariff_and_bands(self, text: str, out: ExtractionOutcome) -> None:
        f = out.fields
        # The bill carries two consumption views: "Consumo rilevato" (physical
        # F1/F2/F3 split from the meter) and "Consumo fatturato" (billing view,
        # often Mono on monoraria offers). Parse each block separately and keep
        # the F-block when present — it is the richer information.
        starts = list(re.finditer(r"Consumo (?:rilevato|fatturato) \(dal", text, re.IGNORECASE))
        blocks: list[tuple[list[str], list[float]]] = []
        for i, m in enumerate(starts):
            end = starts[i + 1].start() if i + 1 < len(starts) else m.end() + 700
            lines = [l.strip() for l in text[m.end():end].splitlines() if l.strip()]
            labels = [l for l in lines if re.fullmatch(r"F[123]|Mono|Totale (energia|consumo)", l)]
            values: list[float] = []
            for l in lines:
                vm = re.fullmatch(r"([\d.,]+)\s*kWh", l)
                if vm:
                    v = parse_number(vm.group(1))
                    if v is not None:
                        values.append(v)
            blocks.append((labels, values))

        all_labels = [l for labels, _ in blocks for l in labels]
        chosen = next((b for b in blocks if {"F1", "F2", "F3"}.issubset(set(b[0]))), None)
        if chosen is None:
            chosen = next((b for b in blocks if "Mono" in b[0]), None)
        if chosen:
            labels, values = chosen
            band_labels = [l for l in labels if re.fullmatch(r"F[123]|Mono", l)]
            if band_labels and len(values) >= len(band_labels):
                for label, v in zip(band_labels, values):
                    out.bands.append(TimeBand(label=label, kwh=v))
        if "Mono" in all_labels or re.search(r"unico per le ore", text, re.IGNORECASE):
            f["tariff_type"] = ExtractedValue("Monoraria", 0.9, "consumption block")
        elif {"F1", "F2", "F3"}.issubset(set(all_labels)):
            f["tariff_type"] = ExtractedValue("Trifaria F1/F2/F3", 0.9, "consumption block")

    def _readings(self, text: str, f: dict) -> None:
        m = re.search(r"Riepilogo delle letture", text, re.IGNORECASE)
        if not m:
            return
        block = text[m.end(): m.end() + 900]
        rows: list[tuple[str, list[float]]] = []
        for rm in re.finditer(r"(\d{2}/\d{2}/\d{4})\s*\n((?:[\d.,]+\s*(?:\n|$)){1,3})", block):
            nums = [n for n in ex.find_numbers(rm.group(2)) if n is not None]
            if nums:
                rows.append((rm.group(1), nums))
        if len(rows) < 2:
            return
        # The table lists the readings of the whole period; the billed delta
        # spans from the first (boundary) reading to the last.
        (d_prev, nums_prev), (d_curr, nums_curr) = rows[0], rows[-1]
        f["previous_reading"] = ExtractedValue(round(sum(nums_prev), 1), 0.7, "letture table")
        f["current_reading"] = ExtractedValue(round(sum(nums_curr), 1), 0.7, "letture table")
        prev_d, curr_d = parse_date(d_prev), parse_date(d_curr)
        if prev_d:
            f["reading_start_date"] = ExtractedValue(prev_d, 0.7, "")
        if curr_d:
            f["reading_end_date"] = ExtractedValue(curr_d, 0.7, "")
