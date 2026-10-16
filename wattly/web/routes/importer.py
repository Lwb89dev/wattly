"""Bill import: upload, bulk auto-import, pipeline status, review & confirm."""

from __future__ import annotations

from types import SimpleNamespace

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, send_file,
    session as flask_session, url_for,
)

from wattly.database.repositories import BillRepository, DocumentRepository
from wattly.services.bill_service import BillService
from wattly.services.import_service import ImportService
from wattly.web import forms
from wattly.web.utils import (
    get_config, gettext, json_error, json_ok, load_settings, ocr_enabled, session_scope,
)

bp = Blueprint("import", __name__, url_prefix="/import")


def _snapshot_key(doc_id: int) -> str:
    return forms.SNAPSHOT_PREFIX + str(doc_id)


def _ocr_status() -> tuple[bool, str]:
    from wattly.parsing.ocr_engine import ocr_available

    return ocr_available()


# --------------------------------------------------------------------- #
@bp.get("")
def index():
    ocr_ok, ocr_reason = _ocr_status()
    with session_scope() as s:
        svc = ImportService(s, get_config())
        docs = svc.docs.recent(10)
        bills = BillRepository(s)
        doc_rows = [{"doc": d, "bills": bills.by_document(d.id) if d.id else []} for d in docs]
        pending_count = len(svc.pending_documents())
    return render_template(
        "import/index.html", docs=doc_rows, ocr_ok=ocr_ok, ocr_reason=ocr_reason,
        ocr_enabled=ocr_enabled(), pending_count=pending_count,
    )


# --------------------------------------------------------------------- #
@bp.post("/upload")
def upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        return json_error("No file received.")
    with session_scope() as s:
        svc = ImportService(s, get_config())
        doc, warning = svc.store_upload(file)
    if doc is None:
        return json_error(warning or "Upload failed.")
    if warning == "duplicate-exact":
        return json_ok(doc_id=doc.id, filename=doc.original_filename, duplicate=True,
                       message="This exact file was already imported.")
    return json_ok(doc_id=doc.id, filename=doc.original_filename, duplicate=False)


# --------------------------------------------------------------------- #
@bp.post("/auto")
def auto():
    """Analyze & import every pending document (bulk flow)."""
    with session_scope() as s:
        svc = ImportService(s, get_config())
        report = svc.auto_import(ocr_enabled())
        pending = len(svc.pending_documents())
    return json_ok(pending=pending, **report)


# --------------------------------------------------------------------- #
@bp.get("/doc/<int:doc_id>/raw")
def raw(doc_id: int):
    with session_scope() as s:
        doc = DocumentRepository(s).get(doc_id)
        if doc is None:
            abort(404)
        return send_file(doc.stored_path, mimetype="application/pdf",
                         download_name=doc.original_filename)


# --------------------------------------------------------------------- #
@bp.get("/review/<int:doc_id>")
def review(doc_id: int):
    bill_id = request.args.get("bill_id", type=int)
    refresh = request.args.get("refresh") == "1"
    key = _snapshot_key(doc_id)
    if refresh or key not in flask_session:
        with session_scope() as s:
            result = ImportService(s, get_config()).parse_document(doc_id, ocr_enabled())
        flask_session[key] = forms.snapshot_from_result(result)
        if result.error:
            flash(gettext("flash.extraction_failed", err=result.error), "error")
    snap = flask_session.get(key)
    if snap is None:
        abort(404)
    locale = load_settings().get("locale", "it")
    with session_scope() as s:
        bill = BillService(s).get(bill_id) if bill_id else None
        doc = DocumentRepository(s).get(doc_id)
    values = forms.values_for_snapshot(snap, locale)
    confidences = snap.get("field_confidence", {})
    return render_template(
        "import/review.html", v=values, errors={}, confidences=confidences,
        warnings=snap.get("warnings", []), confidence=snap.get("confidence", 0.0),
        parse_method=snap.get("parse_method", ""), doc=doc, bill=bill,
    )


@bp.post("/review/<int:doc_id>")
def confirm(doc_id: int):
    locale = load_settings().get("locale", "it")
    bill_id = request.form.get("bill_id", type=int)
    bill, errors = forms.parse_bill_form(request.form, locale)
    key = _snapshot_key(doc_id)
    snap = flask_session.get(key)

    with session_scope() as s:
        svc = BillService(s)
        existing = svc.get(bill_id) if bill_id else None
        if bill_id and existing is None:
            abort(404)

        if errors:
            doc = DocumentRepository(s).get(doc_id)
            values = forms.values_for_bill(bill, locale)
            confidences = (snap or {}).get("field_confidence", {})
            return render_template(
                "import/review.html", v=values, errors=errors, confidences=confidences,
                warnings=(snap or {}).get("warnings", []),
                confidence=(snap or {}).get("confidence", 0.0),
                parse_method=(snap or {}).get("parse_method", ""), doc=doc,
                bill=existing,
            ), 422

        parsed_ns = None
        if snap:
            parsed_ns = SimpleNamespace(
                fields=snap.get("fields", {}),
                confidence=snap.get("confidence"),
                parse_method=snap.get("parse_method", "text"),
            )
        if existing is not None:
            bill.id = existing.id
            bill.document_id = existing.document_id
            bill.field_sources = dict(existing.field_sources or {})
            corrected = forms.diff_corrected(bill, snap)
            if corrected:
                sources = bill.field_sources
                for c in corrected:
                    sources[c] = "corrected"
            if parsed_ns is not None:
                bill.parse_method = parsed_ns.parse_method
                bill.parse_confidence = parsed_ns.confidence
                for fkey in parsed_ns.fields:
                    bill.field_sources.setdefault(fkey, "auto")
            saved = svc.update(bill)
            flask_session.pop(key, None)
            flash(gettext("flash.reparse_updated"), "success")
            return redirect(url_for("bills.detail", bill_id=saved.id))

        bill.document_id = doc_id
        if snap:
            for fkey in forms.diff_corrected(bill, snap):
                bill.field_sources[fkey] = "corrected"
        import_svc = ImportService(s, get_config())
        saved, duplicates = import_svc.confirm_bill(bill, parsed_ns)

    flask_session.pop(key, None)
    flash(gettext("flash.bill_saved"), "success")
    if duplicates:
        flash(gettext("flash.duplicate_note",
                      ids=", ".join("#" + str(d.id) for d in duplicates)), "warning")
    return redirect(url_for("bills.detail", bill_id=saved.id))
