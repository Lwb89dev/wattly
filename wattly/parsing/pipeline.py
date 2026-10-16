"""Import pipeline orchestration.

Stages (each writes an audit log entry):
  1. read     — text extraction with a coverage probe
  2. ocr      — fallback rendering + OCR when coverage is poor
  3. parse    — provider detection + field extraction
  4. validate — cross-field checks + confidence aggregation
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wattly.core.models import TimeBand
from wattly.parsing import ocr_engine, pdf_reader
from wattly.parsing.provider_parsers import PARSERS, detect_parser
from wattly.parsing.provider_parsers.base import ExtractionOutcome

FIELD_WEIGHTS = {
    "total_amount_cents": 0.22,
    "total_kwh": 0.22,
    "billing_period_start": 0.12,
    "billing_period_end": 0.12,
    "issue_date": 0.08,
    "provider_name": 0.06,
    "pod_identifier": 0.05,
    "fixed_charges_cents": 0.04,
    "energy_charges_cents": 0.04,
    "taxes_and_fees_cents": 0.05,
}

COVERAGE_THRESHOLD = 0.5


@dataclass
class ParsedBillResult:
    """Normalized extraction output consumed by the review screen."""

    fields: dict[str, Any] = field(default_factory=dict)
    field_confidence: dict[str, float] = field(default_factory=dict)
    field_notes: dict[str, str] = field(default_factory=dict)
    bands: list[TimeBand] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    parse_method: str = "text"
    ocr_used: bool = False
    page_count: int = 0
    parser_name: str = "generic"
    logs: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_bill(self, document_id: int | None = None) -> "Bill":
        """Convert straight into a domain Bill (used by auto-import)."""
        from wattly.core.models import Bill

        f = self.fields
        bill = Bill(
            document_id=document_id,
            provider_name=f.get("provider_name") or "",
            account_number=f.get("account_number"),
            pod_identifier=f.get("pod_identifier"),
            issue_date=f.get("issue_date"),
            billing_period_start=f.get("billing_period_start"),
            billing_period_end=f.get("billing_period_end"),
            total_amount_cents=f.get("total_amount_cents"),
            total_kwh=f.get("total_kwh"),
            fixed_charges_cents=f.get("fixed_charges_cents"),
            energy_charges_cents=f.get("energy_charges_cents"),
            taxes_and_fees_cents=f.get("taxes_and_fees_cents"),
            previous_reading=f.get("previous_reading"),
            current_reading=f.get("current_reading"),
            reading_start_date=f.get("reading_start_date"),
            reading_end_date=f.get("reading_end_date"),
            tariff_type=f.get("tariff_type"),
            parse_method=self.parse_method,
            parse_confidence=self.confidence,
            field_sources={k: "auto" for k in f},
            time_bands=list(self.bands),
        )
        return bill

    def _log(self, step: str, status: str, message: str, confidence: float | None = None,
             excerpt: str | None = None) -> None:
        self.logs.append(
            {"step": step, "status": status, "message": message,
             "confidence": confidence, "excerpt": (excerpt or "")[:600]}
        )


class ImportPipeline:
    def __init__(self, ocr_enabled: bool = True, locale: str = "it") -> None:
        self.ocr_enabled = ocr_enabled
        self.locale = locale

    def parse(self, path: str | Path) -> ParsedBillResult:
        result = ParsedBillResult()
        path = str(path)
        try:
            doc = self._read(path, result)
            outcome = self._extract(doc, result)
            self._finalize(outcome, result)
        except Exception as exc:  # never propagate: graceful failure + full trace
            result.error = f"{type(exc).__name__}: {exc}"
            result._log("pipeline", "error", result.error, excerpt=traceback.format_exc())
        return result

    # ------------------------------------------------------------------ #
    def _read(self, path: str, result: ParsedBillResult):
        coverage = 0.0
        try:
            coverage = pdf_reader.text_coverage(path)
        except Exception as exc:
            result._log("read", "error", f"Cannot open PDF: {exc}")
            raise
        result.page_count = len(pdf_read_pages(path))
        if coverage >= COVERAGE_THRESHOLD:
            doc = pdf_reader.extract_text_pdf(path)
            result.parse_method = "text"
            result._log("read", "ok", f"Text extraction: coverage {coverage:.0%}, "
                                      f"{doc.page_count} page(s).", confidence=1.0)
            return doc
        result._log("read", "warn", f"Low text coverage ({coverage:.0%}) — document looks scanned.")
        if not self.ocr_enabled:
            result._log("ocr", "skipped", "OCR disabled in settings; trying raw text anyway.")
            result.parse_method = "text-partial"
            return pdf_reader.extract_text_pdf(path)
        available, reason = ocr_engine.ocr_available()
        if not available:
            result._log("ocr", "unavailable",
                        f"{reason}. Trying raw text extraction anyway.")
            result.parse_method = "text-partial"
            return pdf_reader.extract_text_pdf(path)
        doc = ocr_engine.ocr_pdf(path)
        result.ocr_used = True
        result.parse_method = "ocr"
        chars = sum(len(p.text.strip()) for p in doc.pages)
        result._log("ocr", "ok" if chars > 200 else "warn",
                    f"OCR extracted {chars} characters across {doc.page_count} page(s).",
                    confidence=min(1.0, chars / 2500))
        return doc

    def _extract(self, doc, result: ParsedBillResult) -> ExtractionOutcome:
        parser = detect_parser(doc, PARSERS)
        result.parser_name = parser.name
        outcome = parser.parse(doc)
        result._log("parse", "ok",
                    f"Parser '{parser.name}' extracted "
                    f"{len(outcome.fields)} fields, {len(outcome.bands)} time band(s).")
        return outcome

    def _finalize(self, outcome: ExtractionOutcome, result: ParsedBillResult) -> None:
        for key, ev in outcome.fields.items():
            result.fields[key] = ev.value
            result.field_confidence[key] = round(ev.confidence, 2)
            if ev.note:
                result.field_notes[key] = ev.note
        result.bands = outcome.bands
        result.warnings = list(outcome.warnings)

        w_sum = c_sum = 0.0
        for key, w in FIELD_WEIGHTS.items():
            if key in result.field_confidence:
                w_sum += w
                c_sum += w * result.field_confidence[key]
        result.confidence = round(c_sum / w_sum, 3) if w_sum else 0.0
        if not result.fields:
            result.warnings.append("No fields could be extracted — please enter the data manually.")
            result._log("validate", "warn", "No fields extracted.", confidence=0.0)
        else:
            status = "ok" if result.confidence >= 0.75 else "warn"
            result._log("validate", status,
                        f"Overall confidence {result.confidence:.0%}; "
                        f"{len(result.warnings)} warning(s).",
                        confidence=result.confidence)


def pdf_read_pages(path: str) -> list:
    try:
        import fitz

        with fitz.open(path) as doc:
            return list(doc)
    except Exception:
        pass
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return list(pdf.pages)
    except Exception:
        return []
