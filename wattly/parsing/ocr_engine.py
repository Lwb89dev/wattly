"""OCR fallback for scanned / image-based PDFs.

Tesseract is an optional system dependency: everything here
feature-detects it and degrades gracefully (the app keeps working for
text PDFs and manual entry when tesseract is missing).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from wattly.parsing.pdf_reader import PageContent, ParsedDocument


def ocr_available() -> tuple[bool, str]:
    """Return (available, reason-if-not)."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False, "pytesseract is not installed"
    try:
        import fitz  # noqa: F401
    except ImportError:
        return False, "page rendering (PyMuPDF) is not available on this platform"
    if not shutil.which("tesseract"):
        return False, "tesseract binary not found (install tesseract-ocr)"
    return True, ""


def preprocess_image(img):
    """Light preprocessing: grayscale + autocontrast. Deliberately gentle:
    aggressive binarization destroys small print on noisy scans."""
    from PIL import ImageOps

    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img, cutoff=1)
    return img


def ocr_pdf(path: str | Path, dpi: int = 300, lang: str = "ita+eng") -> ParsedDocument:
    """Render each page and OCR it into a ParsedDocument."""
    import fitz
    import pytesseract

    path = str(path)
    parsed = ParsedDocument(path=path, source="ocr")
    doc = fitz.open(path)
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img = _pixmap_to_pil(pix)
            img = preprocess_image(img)
            try:
                text = pytesseract.image_to_string(img, lang=lang) or ""
            except Exception:
                # e.g. missing 'ita' tessdata — retry with English only.
                text = pytesseract.image_to_string(img, lang="eng") or ""
            parsed.pages.append(PageContent(number=i + 1, text=text))
    finally:
        doc.close()
    return parsed


def _pixmap_to_pil(pix):
    from PIL import Image

    mode = "RGB" if pix.n >= 3 else "L"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)
