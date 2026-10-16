"""Low-level text extraction helpers shared by provider parsers.

Everything here operates on plain strings: keyword windows, date /
amount / kWh candidate finders with locale-aware normalization and
basic plausibility filtering (e.g. years are not amounts).
"""

from __future__ import annotations

import re
from datetime import date

from wattly.parsing.normalization import parse_amount_to_cents, parse_date, parse_number

AMOUNT_RE = re.compile(r"\d{1,3}(?:[.\s\xa0]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?")
KWH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:k\s*[Ww]\s*/?\s*h(?:ora)?|chilowattora)", re.IGNORECASE)
READING_RE = re.compile(r"\d{1,3}(?:[.\s\xa0]\d{3})+(?:,\d{1,3})?|\d+(?:[.,]\d+)?")


def iter_keyword_windows(text: str, keywords: list[str], radius: int = 140):
    """Yield (keyword, substring) for each case-insensitive keyword hit."""
    low = text.lower()
    for kw in keywords:
        start = 0
        while True:
            idx = low.find(kw.lower(), start)
            if idx < 0:
                break
            lo = max(0, idx - radius // 3)
            hi = min(len(text), idx + len(kw) + radius)
            yield kw, text[lo:hi]
            start = idx + len(kw)


def find_dates(s: str) -> list[date]:
    """All parseable dates in a string, in order of appearance."""
    out: list[date] = []
    for m in re.finditer(
        r"\b\d{1,2}[/.]\d{1,2}[/.]\d{4}\b|\b\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4}\b", s
    ):
        d = parse_date(m.group(0))
        if d and d not in out:
            out.append(d)
    return out


def find_amounts(s: str, min_cents: int = 50, max_cents: int = 2_000_000) -> list[int]:
    """All plausible monetary amounts (integer cents), years excluded."""
    out: list[int] = []
    for m in AMOUNT_RE.finditer(s):
        raw = m.group(0)
        # A bare 4-digit 19xx/20xx number is almost certainly a year.
        if re.fullmatch(r"(?:19|20)\d{2}", raw):
            continue
        cents = parse_amount_to_cents(raw)
        if cents is not None and min_cents <= cents <= max_cents and cents not in out:
            out.append(cents)
    return out


def find_kwh(s: str) -> list[float]:
    """All kWh values found next to a kWh unit suffix."""
    out: list[float] = []
    for m in KWH_RE.finditer(s):
        v = parse_number(m.group(1))
        if v is not None and 1 <= v <= 100_000 and v not in out:
            out.append(v)
    return out


def find_numbers(s: str) -> list[float]:
    out: list[float] = []
    for m in READING_RE.finditer(s):
        raw = m.group(0)
        if re.fullmatch(r"(?:19|20)\d{2}", raw):
            continue
        v = parse_number(raw)
        if v is not None and v not in out:
            out.append(v)
    return out


def amount_after_label(
    text: str,
    pattern: str,
    min_cents: int = 50,
    max_lines: int = 3,
    euro_line: str = "first",
    case_sensitive: bool = False,
) -> int | None:
    """First monetary amount following an anchor regex.

    Italian bills often place the value on the line(s) after the label,
    sometimes with the label itself wrapping across lines. Prefers lines
    bearing the € symbol (skips quantity rows like "8 kWh x").

    ``euro_line`` selects which €-bearing line holds the value: ``"first"``
    for label-then-value layouts (Enel component rows, where a wrapped label
    could otherwise bleed into the next row), ``"last"`` for multi-line
    quantity rows where the row total comes last
    ("8 kWh x 0,23 €/kWh 1,87 €").

    ``case_sensitive`` with a ``^…$`` line-anchored pattern distinguishes
    detail rows ("Quota fissa") from uppercase section headers
    ("QUOTA FISSA E QUOTA POTENZA") that mention the same words.
    """
    import re as _re

    flags = 0 if case_sensitive else _re.IGNORECASE
    m = _re.search(pattern, text, flags | _re.MULTILINE)
    if not m:
        return None
    checked = 0
    euro_amounts: list[int] = []
    fallback: int | None = None
    for line in text[m.end():].splitlines():
        s = line.strip()
        if not s:
            continue
        checked += 1
        if checked > max_lines:
            break
        amounts = find_amounts(s, min_cents=min_cents)
        if not amounts:
            continue
        if "€" in s or "eur" in s.lower():
            euro_amounts.append(amounts[-1])
        elif fallback is None:
            fallback = amounts[-1]
    if euro_amounts:
        return euro_amounts[0] if euro_line == "first" else euro_amounts[-1]
    return fallback
