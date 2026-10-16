"""Generic provider parser: keyword/regex field locators.

Designed for robustness across unknown layouts: every field uses
multiple strategies (keyword line -> pattern -> fallback), each
returning a confidence score. Fields it cannot find are simply absent
from the outcome — the review form lets the user fill the gaps.
"""

from __future__ import annotations

import re

from wattly.core.models import TimeBand
from wattly.parsing import extractor as ex
from wattly.parsing.normalization import normalize_band_label, parse_date
from wattly.parsing.pdf_reader import ParsedDocument
from wattly.parsing.provider_parsers.base import (
    ExtractedValue,
    ExtractionOutcome,
    ProviderParser,
)

KNOWN_PROVIDERS = [
    "enel energia", "enel", "sorgenia", "a2a", "acea", "edison", "illumia",
    "engie", "hera", "irene", "green network", "luceverde", "e-distribuzione",
    "dolomiti energia", "südtirol energia", "aldi energy", "plenitude",
    "windtre energy", "very", "tiscali energy", "eni", "cad energia", "octopus",
]

MONTH_RANGE_RE = re.compile(
    r"dal\s+(\d{1,2}[/.]\d{1,2}[/.]\d{4})\s+al\s+(\d{1,2}[/.]\d{1,2}[/.]\d{4})",
    re.IGNORECASE,
)


class GenericProviderParser(ProviderParser):
    name = "generic"

    def fingerprint(self, doc: ParsedDocument) -> float:
        return 0.0  # generic parser never claims a document

    def parse(self, doc: ParsedDocument) -> ExtractionOutcome:
        text = doc.full_text
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        out = ExtractionOutcome()
        f = out.fields

        self._provider(lines, f)
        self._pod(text, f)
        self._account(text, f)
        self._issue_date(text, f)
        self._period(text, f, out)
        self._total(text, f)
        self._kwh(text, f)
        self._components(text, f)
        self._tariff(text, f)
        self._readings(text, f)
        self._bands(doc, out)

        self._cross_checks(out)
        return out

    # ------------------------------------------------------------------ #
    @staticmethod
    def _keyword_lines(text: str, keywords: list[str], radius: int = 150):
        """Yield (keyword, line) pairs: every line containing a keyword."""
        for kw, win in ex.iter_keyword_windows(text, keywords, radius):
            for line in win.splitlines():
                if kw.lower() in line.lower():
                    yield kw, line

    def _provider(self, lines: list[str], f: dict) -> None:
        head = lines[:12]
        for line in head:
            low = line.lower()
            for name in KNOWN_PROVIDERS:
                if name in low and len(line) <= 60:
                    f["provider_name"] = ExtractedValue(line, 0.85, f"matched '{name}'")
                    return
        for line in head:
            if re.search(r"s\.\s?p\.\s?a|s\.\s?r\.\s?l|energia", line, re.I) and len(line) <= 70:
                f["provider_name"] = ExtractedValue(line, 0.45, "company-suffix heuristic")
                return

    def _pod(self, text: str, f: dict) -> None:
        m = re.search(r"\bIT[0-9A-Z]{12}\b", text.upper())
        if m:
            f["pod_identifier"] = ExtractedValue(m.group(0), 0.9, "POD pattern IT+12")
            return
        for kw, win in ex.iter_keyword_windows(text, ["pod", "punto di prelievo"], 120):
            m = re.search(r"\b([A-Z0-9]{14})\b", win.upper())
            if m:
                f["pod_identifier"] = ExtractedValue(m.group(1), 0.55, "keyword window")
                return

    def _account(self, text: str, f: dict) -> None:
        for kw, line in self._keyword_lines(
            text, ["numero cliente", "codice cliente", "cliente", "utenza", "contratto", "matricola"]
        ):
            m = re.search(r"(\d[\d\-/]{3,}\d)", line)
            if m:
                f["account_number"] = ExtractedValue(m.group(1), 0.6, f"near '{kw}'")
                return

    def _issue_date(self, text: str, f: dict) -> None:
        for kw, line in self._keyword_lines(
            text, ["data emissione", "data documento", "emessa il", "emesso il", "data fattura"]
        ):
            dates = ex.find_dates(line)
            if dates:
                f["issue_date"] = ExtractedValue(dates[0], 0.9, f"near '{kw}'")
                return
        dates = ex.find_dates(text[:1500])
        if dates:
            f["issue_date"] = ExtractedValue(dates[0], 0.35, "first date in document")

    def _period(self, text: str, f: dict, out: ExtractionOutcome) -> None:
        matches = list(MONTH_RANGE_RE.finditer(text))
        if matches:
            # Bills often mention several date ranges (annual summaries,
            # offer validity…): the billing period is the one near words
            # like "rilevato"/"fatturato", not necessarily the first.
            def score(m: re.Match) -> int:
                ctx = text[max(0, m.start() - 80): m.start()].lower()
                if re.search(r"rilevat|fatturat|riferimento", ctx):
                    return 2
                if "periodo" in ctx or "consumo" in ctx:
                    return 1
                return 0

            m = max(matches, key=score)
            start, end = parse_date(m.group(1)), parse_date(m.group(2))
            if start and end:
                conf = 0.9 if score(m) == 2 else (0.7 if score(m) == 1 else 0.5)
                f["billing_period_start"] = ExtractedValue(start, conf, "'dal ... al ...'")
                f["billing_period_end"] = ExtractedValue(end, conf, "'dal ... al ...'")
                return
        for kw, win in ex.iter_keyword_windows(text, ["periodo", "fatturazione"], 170):
            dates = ex.find_dates(win)
            if len(dates) >= 2:
                conf = 0.6 if ("dal" in win.lower() and "al" in win.lower()) else 0.45
                f["billing_period_start"] = ExtractedValue(dates[0], conf, f"near '{kw}'")
                f["billing_period_end"] = ExtractedValue(dates[1], conf, f"near '{kw}'")
                return

    def _total(self, text: str, f: dict) -> None:
        # Prefer amounts on €-bearing lines mentioning a total keyword
        # (avoids confusing "Consumo totale: 347 kWh" with the amount);
        # ties are broken by position — the final total line comes last.
        tiered: list[tuple[int, int, int]] = []  # (tier, position, value)
        for kw, win in ex.iter_keyword_windows(text, ["totale", "importo", "addebito", "pagare", "pagamento"], 150):
            for line in win.splitlines():
                low = line.lower()
                if kw.lower() not in low:
                    continue
                amounts = ex.find_amounts(line, min_cents=500)
                if not amounts:
                    continue
                has_euro = "€" in line or "eur" in low
                tiered.append((2 if has_euro else 1, len(tiered), max(amounts)))
        if tiered:
            tier = max(t[0] for t in tiered)
            top = [t for t in tiered if t[0] == tier]
            best = max(top, key=lambda t: t[1])
            conf = 0.9 if tier == 2 else 0.55
            f["total_amount_cents"] = ExtractedValue(
                best[2], conf, "€ line near total" if tier == 2 else "line near total")
            return
        amounts = ex.find_amounts(text, min_cents=1_000)
        if amounts:
            f["total_amount_cents"] = ExtractedValue(max(amounts), 0.3, "largest amount in doc")

    def _kwh(self, text: str, f: dict) -> None:
        scored: list[tuple[float, float]] = []  # (score, value)
        for m in ex.KWH_RE.finditer(text):
            v = ex.parse_number(m.group(1))
            if v is None or not 5 <= v <= 50_000:
                continue
            lo, hi = max(0, m.start() - 90), min(len(text), m.end() + 60)
            ctx = text[lo:hi].lower()
            score = 0.45
            if re.search(r"consum|prelev|fattur", ctx):
                score = 0.8
            if re.search(r"totale|tot\b", ctx):
                score = 0.95
            if re.search(r"giornalier|al giorno|medio", ctx):
                score -= 0.3  # daily average, not the billed total
            if re.search(r"f[123]\b|fascia", ctx):
                score -= 0.15  # band value, total preferred
            scored.append((score, v))
        if scored:
            scored.sort(key=lambda t: (t[0], t[1]))
            score, v = scored[-1]
            f["total_kwh"] = ExtractedValue(round(v, 1), max(0.2, min(score, 1.0)), "kWh context scoring")

    def _components(self, text: str, f: dict) -> None:
        def _amount_near(keywords: list[str]) -> int | None:
            vals: list[int] = []
            for kw, line in self._keyword_lines(text, keywords):
                vals.extend(ex.find_amounts(line, min_cents=100, max_cents=300_000))
            return max(vals) if vals else None

        fixed = _amount_near(["quota fissa", "costo fisso", "canone", "potenza e contatore"])
        if fixed is not None:
            f["fixed_charges_cents"] = ExtractedValue(fixed, 0.5, "keyword line")
        energy = _amount_near(
            ["spesa per l'energia", "energia elettrica", "materia energia", "energia venduta",
             "costo energia", "prezzo energia", "vendita energia", "fornitura energia"]
        )
        if energy is not None:
            f["energy_charges_cents"] = ExtractedValue(energy, 0.5, "keyword line")
        # Taxes often share one line with several keywords — sum each
        # distinct amount value once.
        taxes: list[int] = []
        for kw, line in self._keyword_lines(
            text, ["accise", "imposte", "tasse", "oneri", "addizionali", "tributi"]
        ):
            for cents in ex.find_amounts(line, min_cents=100, max_cents=300_000):
                if cents not in taxes:
                    taxes.append(cents)
        if taxes:
            f["taxes_and_fees_cents"] = ExtractedValue(sum(taxes), 0.45, "distinct tax amounts")

    def _tariff(self, text: str, f: dict) -> None:
        low = text.lower()
        if "monorari" in low:
            f["tariff_type"] = ExtractedValue("Monoraria", 0.6, "keyword")
        elif "biorari" in low:
            f["tariff_type"] = ExtractedValue("Bioraria", 0.6, "keyword")
        elif "trifari" in low or ("f1" in low and "f2" in low and "f3" in low):
            f["tariff_type"] = ExtractedValue("Trifaria F1/F2/F3", 0.55, "keyword")

    def _readings(self, text: str, f: dict) -> None:
        def _reading(keywords: list[str], field: str, date_field: str) -> None:
            for kw, line in self._keyword_lines(text, keywords):
                nums = [n for n in ex.find_numbers(line) if 10 <= n < 1_000_000]
                if nums:
                    f[field] = ExtractedValue(max(nums), 0.6, f"near '{kw}'")
                    dates = ex.find_dates(line)
                    if dates:
                        f[date_field] = ExtractedValue(dates[0], 0.4, "")
                    return

        _reading(["lettura precedente", "lettura iniziale", "lettura antecedente"],
                 "previous_reading", "reading_start_date")
        _reading(["lettura attuale", "lettura finale", "lettura corrente"],
                 "current_reading", "reading_end_date")

    def _bands(self, doc: ParsedDocument, out: ExtractionOutcome) -> None:
        bands: dict[str, TimeBand] = {}
        # 1) tables (pdfplumber): row label in first cell
        for page in doc.pages:
            for table in page.tables:
                for row in table:
                    cells = [(c or "").strip() for c in row]
                    if not any(cells):
                        continue
                    label = normalize_band_label(cells[0])
                    if not label or label in bands:
                        continue
                    nums = ex.find_numbers(" | ".join(cells[1:]))
                    kwh_vals = [n for n in nums if 1 <= n <= 50_000]
                    if not kwh_vals:
                        continue
                    band = TimeBand(label=label, kwh=kwh_vals[0])
                    amounts = ex.find_amounts(" | ".join(cells[1:]), min_cents=100)
                    if len(amounts) >= 2:
                        band.amount_cents = amounts[-1]
                    bands[label] = band
        # 2) free text: "F1 ... 123 kWh" — the kWh must be on the same line
        # (skips "Contratto: TRIFARIA F1/F2/F3" style mentions).
        if not bands:
            text = doc.full_text
            for m in re.finditer(
                r"\b(F[123]|Fascia\s*[123]|fascia\s*(?:blu|arancio|gialla))\b", text, re.IGNORECASE
            ):
                line_end = text.find("\n", m.end())
                win = text[m.end(): line_end if line_end != -1 else len(text)]
                vals = ex.find_kwh(win)
                if vals:
                    label = normalize_band_label(m.group(1))
                    if label and label not in bands:
                        bands[label] = TimeBand(label=label, kwh=vals[0])
        order = {"F1": 1, "F2": 2, "F3": 3, "Mono": 0}
        out.bands = sorted(bands.values(), key=lambda b: order.get(b.label, 9))

    # ------------------------------------------------------------------ #
    def _cross_checks(self, out: ExtractionOutcome) -> None:
        from wattly.parsing.provider_parsers.base import validate_outcome

        validate_outcome(out)
