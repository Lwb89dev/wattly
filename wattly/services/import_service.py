"""Import service: upload -> pipeline -> review -> persisted bill."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from wattly.config import Config
from wattly.core.models import Bill, DocumentInfo
from wattly.database.repositories import BillRepository, DocumentRepository, LogRepository
from wattly.parsing import ImportPipeline, ParsedBillResult

ALLOWED_EXTENSIONS = {".pdf"}


class ImportService:
    def __init__(self, session: Session, config: Config) -> None:
        self.session = session
        self.config = config
        self.docs = DocumentRepository(session)
        self.bills = BillRepository(session)
        self.logs = LogRepository(session)

    # ------------------------------------------------------------------ #
    def store_upload(self, file: FileStorage) -> tuple[DocumentInfo | None, str | None]:
        """Persist the uploaded file; returns (document, warning).

        ``warning`` is "duplicate-exact" when the very same file was
        already imported, or an error message when the upload is invalid.
        """
        filename = (file.filename or "upload.pdf").strip() or "upload.pdf"
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return None, f"'{ext or 'file'}' is not supported — please upload a PDF."
        data = file.read()
        if not data:
            return None, "The uploaded file is empty."
        sha = hashlib.sha256(data).hexdigest()

        existing = self.docs.by_sha256(sha)
        if existing is not None:
            return existing, "duplicate-exact"

        self.config.documents_dir.mkdir(parents=True, exist_ok=True)
        stored = self.config.documents_dir / f"{sha}{ext}"
        if not stored.exists():
            stored.write_bytes(data)
        info = DocumentInfo(
            id=None, sha256=sha, original_filename=filename,
            stored_path=str(stored), mime_type=file.mimetype, page_count=None,
            ocr_used=False,
        )
        self.docs.create(info)
        self.logs.add("upload", "ok", f"Stored '{filename}' ({len(data)} bytes).",
                      document_id=info.id)
        self.session.commit()
        return info, None

    # ------------------------------------------------------------------ #
    def parse_document(self, doc_id: int, ocr_enabled: bool = True) -> ParsedBillResult:
        """Run the extraction pipeline on a stored document (audit-logged)."""
        doc = self.docs.get(doc_id)
        if doc is None:
            raise LookupError(f"Document {doc_id} not found")
        pipeline = ImportPipeline(ocr_enabled=ocr_enabled)
        result = pipeline.parse(doc.stored_path)
        self.docs.mark_ocr(doc_id, result.ocr_used, result.page_count or None)
        for entry in result.logs:
            self.logs.add(
                step=entry["step"], status=entry["status"], message=entry["message"],
                confidence=entry.get("confidence"), excerpt=entry.get("excerpt"),
                document_id=doc_id,
            )
        self.session.commit()
        return result

    # ------------------------------------------------------------------ #
    def confirm_bill(
        self,
        bill: Bill,
        parsed: ParsedBillResult | None = None,
    ) -> tuple[Bill, list[Bill]]:
        """Save a reviewed bill; returns (bill, duplicate matches)."""
        if parsed is not None:
            bill.parse_method = parsed.parse_method
            bill.parse_confidence = parsed.confidence
            sources = bill.field_sources or {}
            for key in parsed.fields:
                sources.setdefault(key, "auto")
            bill.field_sources = sources
        else:
            bill.parse_method = bill.parse_method or "manual"
            bill.field_sources = bill.field_sources or {
                k: "manual" for k in (
                    "provider_name", "total_amount_cents", "total_kwh",
                    "billing_period_start", "billing_period_end",
                )
            }
        from wattly.core import calculators

        calculators.recompute_derived(bill)
        saved = self.bills.save(bill)
        self.logs.add(
            "confirm", "ok",
            f"Bill confirmed and saved (source: {bill.parse_method}).",
            confidence=bill.parse_confidence, document_id=bill.document_id,
            bill_id=saved.id,
        )
        self.session.commit()
        return saved, self.bills.find_duplicates(
            saved.provider_name, saved.billing_period_start,
            saved.billing_period_end, exclude_id=saved.id,
        )

    def mark_fields_corrected(self, bill: Bill, corrected: list[str]) -> None:
        sources = dict(bill.field_sources or {})
        for key in corrected:
            sources[key] = "corrected"
        bill.field_sources = sources

    # ------------------------------------------------------------------ #
    # Bulk (automatic) import
    # ------------------------------------------------------------------ #
    AUTO_IMPORT_MIN_CONFIDENCE = 0.80

    def pending_documents(self) -> list[DocumentInfo]:
        """Uploaded documents not linked to any bill yet."""
        return self.docs.unlinked()

    def auto_import(self, ocr_enabled: bool = True) -> dict:
        """Run the pipeline on every pending document.

        Documents that parse cleanly with high confidence are saved as bills
        without manual review; everything else is reported back for the
        review queue. Returns a status report dict (JSON-serializable).
        """
        from types import SimpleNamespace

        report: dict[str, list[dict]] = {"imported": [], "review": [], "duplicates": [], "errors": []}
        for doc in self.pending_documents():
            entry = {"doc_id": doc.id, "filename": doc.original_filename}
            try:
                result = self.parse_document(doc.id, ocr_enabled)
            except Exception as exc:
                report["errors"].append({**entry, "error": str(exc)})
                continue
            entry["confidence"] = result.confidence
            if result.error or not result.fields:
                report["review"].append({**entry, "reason": "failed"})
                continue
            bill = result.to_bill(document_id=doc.id)
            duplicates = self.bills.find_duplicates(
                bill.provider_name, bill.billing_period_start, bill.billing_period_end
            )
            if duplicates:
                report["duplicates"].append(
                    {**entry, "bill_ids": [d.id for d in duplicates]}
                )
                continue
            if result.confidence >= self.AUTO_IMPORT_MIN_CONFIDENCE and not result.warnings:
                parsed_ns = SimpleNamespace(
                    fields=result.fields, confidence=result.confidence,
                    parse_method=result.parse_method,
                )
                saved, _ = self.confirm_bill(bill, parsed_ns)
                report["imported"].append(
                    {**entry, "bill_id": saved.id,
                     "label": (saved.billing_period_start or saved.issue_date).strftime("%b %Y")
                     if (saved.billing_period_start or saved.issue_date) else ""}
                )
            else:
                report["review"].append(
                    {**entry, "reason": "warnings" if result.warnings else "low_confidence"}
                )
        return report

    # ------------------------------------------------------------------ #
    def file_preview_path(self, doc_id: int) -> Path | None:
        doc = self.docs.get(doc_id)
        return Path(doc.stored_path) if doc else None
