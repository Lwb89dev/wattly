"""Provider parser contract, detection logic and shared validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from wattly.core.models import TimeBand
from wattly.parsing.pdf_reader import ParsedDocument


@dataclass
class ExtractedValue:
    value: Any
    confidence: float
    note: str = ""


@dataclass
class ExtractionOutcome:
    """What a provider parser found in a document."""

    fields: dict[str, ExtractedValue] = field(default_factory=dict)
    bands: list[TimeBand] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProviderParser(ABC):
    """Base class for provider-specific bill parsers."""

    name: str = "base"

    @abstractmethod
    def fingerprint(self, doc: ParsedDocument) -> float:
        """0..1 score of how confidently this parser recognises the bill."""

    @abstractmethod
    def parse(self, doc: ParsedDocument) -> ExtractionOutcome:
        """Extract fields from the document."""


def validate_outcome(out: ExtractionOutcome) -> None:
    """Cross-field consistency checks shared by all provider parsers.

    Appends human-readable warnings; never raises.
    """
    f = out.fields
    start = f.get("billing_period_start")
    end = f.get("billing_period_end")
    if start and end and end.value and start.value and end.value < start.value:
        out.warnings.append("Billing period end precedes its start — check the dates.")
        end.value = None
    total_kwh = f.get("total_kwh")
    band_kwh = sum(b.kwh or 0 for b in out.bands)
    if total_kwh and total_kwh.value and band_kwh:
        if abs(band_kwh - total_kwh.value) > max(3.0, total_kwh.value * 0.12):
            out.warnings.append(
                f"Time bands sum to {band_kwh:.0f} kWh but total is "
                f"{total_kwh.value:.0f} kWh — verify band values."
            )
        else:
            total_kwh.confidence = min(1.0, total_kwh.confidence + 0.1)
    total = f.get("total_amount_cents")
    comp = [f.get(k) for k in ("energy_charges_cents", "fixed_charges_cents", "taxes_and_fees_cents")]
    if total and total.value is not None and all(c is not None for c in comp):
        s = sum(c.value for c in comp if c is not None)
        if abs(s - total.value) > 150:
            out.warnings.append(
                f"Component charges sum to {s / 100:.2f} but total is {total.value / 100:.2f}."
            )


def detect_parser(doc: ParsedDocument, parsers: list[type[ProviderParser]]) -> ProviderParser:
    """Instantiate the parser with the highest fingerprint score."""
    generic: ProviderParser | None = None
    best: ProviderParser | None = None
    best_score = 0.0
    for cls in parsers:
        parser = cls()
        if parser.name == "generic":
            generic = parser
            continue
        score = parser.fingerprint(doc)
        if score > best_score:
            best, best_score = parser, score
    if best is not None and best_score >= 0.5:
        return best
    if generic is None:
        raise RuntimeError("No provider parsers registered (generic parser missing)")
    return generic
