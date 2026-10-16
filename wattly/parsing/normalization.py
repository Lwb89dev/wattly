"""Locale-aware normalization of dates and numbers from bill text.

Italian bills dominate the initial target market, so the default number
locale is ``it`` (decimal comma, dot thousands) with automatic fallback
to international formats. Dates support ISO, DD/MM/YYYY and
"15 luglio 2025" / "July 15, 2025" style strings.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

IT_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}

EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

_DATE_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
_MONTH_NAME_RE = re.compile(
    r"\b(\d{1,2})?\s*([A-Za-zÀ-ÿ]+)\s*(\d{4})\b", re.IGNORECASE
)
_MONTH_FIRST_RE = re.compile(
    r"\b([A-Za-zÀ-ÿ]+)\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE
)


def parse_date(text: str | None) -> date | None:
    """Parse a single date string: ISO, DD/MM/YYYY or month-name formats."""
    if not text:
        return None
    text = text.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    m = _DATE_RE.search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = _MONTH_NAME_RE.search(text)
    if m:
        d_s, month_s, y_s = m.group(1), m.group(2).lower(), m.group(3)
        month = IT_MONTHS.get(month_s) or EN_MONTHS.get(month_s)
        if month:
            d = int(d_s) if d_s else 1
            try:
                return date(int(y_s), month, d)
            except ValueError:
                return None
    m = _MONTH_FIRST_RE.search(text)
    if m:
        month_s, d_s, y_s = m.group(1).lower(), m.group(2), m.group(3)
        month = IT_MONTHS.get(month_s) or EN_MONTHS.get(month_s)
        if month:
            try:
                return date(int(y_s), month, int(d_s))
            except ValueError:
                return None
    return None


def parse_number(text: str | None, locale: str = "it") -> float | None:
    """Parse a number written in Italian or international format."""
    if text is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", text.replace("\u00a0", " "))
    if not s or s in {"-", ".", ","}:
        return None
    if "," in s and "." in s:
        # The rightmost separator is the decimal one.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) == 3 and head and len(head.lstrip("-")) > 0:
            # e.g. "1,234" — ambiguous; locale decides.
            if locale == "it":
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif locale == "it" and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        # Dot-only Italian number in strict thousands groups ("2.338"):
        # in Italian the decimal separator is the comma, so dots group thousands.
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_amount_to_cents(text: str | None, locale: str = "it") -> int | None:
    """Parse a monetary string into integer cents (half-up rounding)."""
    n = parse_number(text, locale)
    if n is None:
        return None
    return int(Decimal(str(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def month_year(text: str | None) -> date | None:
    """Parse 'MM/YYYY', 'MM-YYYY' or month-name + year into the 1st of month."""
    if not text:
        return None
    m = re.search(r"\b(\d{1,2})[/\-.](\d{4})\b", text)
    if m:
        try:
            return date(int(m.group(2)), int(m.group(1)), 1)
        except ValueError:
            return None
    return parse_date(text)


def normalize_band_label(text: str | None) -> str | None:
    """Map 'Fascia 1', 'F1', 'peak'... to canonical F1/F2/F3/Mono labels."""
    if not text:
        return None
    s = text.strip().lower()
    if "mono" in s or "unica" in s:
        return "Mono"
    m = re.search(r"f(?:ascia)?\s*0?([123])\b", s)
    if m:
        return f"F{m.group(1)}"
    if "peak" in s or "punta" in s:
        return "F1"
    return None
