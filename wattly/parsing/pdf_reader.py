"""PDF text and layout extraction.

PyMuPDF (fitz) is the primary engine for text + word coordinates;
pdfplumber adds table extraction on top and doubles as the fallback
engine where PyMuPDF is unavailable (e.g. the Android APK). Everything
degrades gracefully: a broken table pass never kills the text pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageContent:
    number: int
    text: str
    words: list[tuple] = field(default_factory=list)  # (x0, y0, x1, y1, word, ...)
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass
class ParsedDocument:
    path: str
    source: str  # "text" | "ocr"
    pages: list[PageContent] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _has_fitz() -> bool:
    try:
        import fitz  # noqa: F401

        return True
    except ImportError:
        return False


def text_coverage(path: str | Path, min_chars_per_page: int = 80) -> float:
    """Fraction of pages that look like they contain real text."""
    path = str(path)
    if not _has_fitz():
        return _text_coverage_pdfplumber(path, min_chars_per_page)
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    if not doc.page_count:
        return 0.0
    good = sum(
        1 for p in doc if len(p.get_text("text").strip()) >= min_chars_per_page
    )
    return good / doc.page_count


def _text_coverage_pdfplumber(path: str, min_chars_per_page: int) -> float:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            return 0.0
        good = sum(
            1 for p in pdf.pages
            if len((p.extract_text() or "").strip()) >= min_chars_per_page
        )
        return good / len(pdf.pages)


def extract_text_pdf(path: str | Path) -> ParsedDocument:
    """Extract text, word positions and tables from a text-based PDF."""
    path = str(path)
    if not _has_fitz():
        return _extract_text_pdfplumber(path)
    import fitz  # PyMuPDF

    parsed = ParsedDocument(path=path, source="text")
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        words = page.get_text("words") or []
        parsed.pages.append(
            PageContent(
                number=i + 1,
                text=page.get_text("text") or "",
                words=[tuple(w) for w in words],
            )
        )
    doc.close()
    _attach_tables(parsed)
    return parsed


def _extract_text_pdfplumber(path: str) -> ParsedDocument:
    """fitz-free path (Android): pdfplumber supplies text, words, tables."""
    import pdfplumber

    parsed = ParsedDocument(path=path, source="text")
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            words = []
            for j, w in enumerate(page.extract_words(extra_attrs=["size"]) or []):
                words.append((w["x0"], w["top"], w["x1"], w["bottom"], w["text"], 0, 0, j))
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            parsed.pages.append(PageContent(number=i + 1, text=text, words=words, tables=tables))
    return parsed


def _attach_tables(parsed: ParsedDocument) -> None:
    """Best-effort table extraction via pdfplumber."""
    try:
        import pdfplumber

        with pdfplumber.open(parsed.path) as pdf:
            for page_content, pl_page in zip(parsed.pages, pdf.pages):
                try:
                    page_content.tables = pl_page.extract_tables() or []
                except Exception:
                    page_content.tables = []
    except Exception:
        pass
