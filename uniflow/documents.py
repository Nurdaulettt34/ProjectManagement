"""US2–US5 document API. Every query is scoped to the current user;
someone else's document is reported as 404."""
import io
import uuid
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request, send_file
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, undefer

from ai.schema import FALLBACK_TYPE
from .auth import login_required_api, login_required_hybrid
from .errors import error
from .extensions import db
from .files import ALLOWED_TYPES, file_extension, has_valid_signature, sha256_hex
from .models import Document, DocumentStatus, FieldState
from .services import classification_message, process_document, summarize_document

bp = Blueprint("documents", __name__, url_prefix="/api/documents")

TYPE_LABELS = {
    "certificate": "Certificate",
    "application_form": "Application form",
    "request": "Request",
    "transcript": "Transcript",
    "id_document": "ID document",
    "internal_form": "Internal form",
    "other": "Other",
}
MAX_FIELD_VALUE = 500


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _iso(dt):
    return dt.isoformat() if dt else None


def classification_dict(doc):
    c = doc.classification
    if c is None:
        return None
    return {
        "type": c.doc_type,
        "label": TYPE_LABELS.get(c.doc_type, c.doc_type),
        "confidence": c.confidence,
        "method": c.method.value,
        "message": classification_message(doc),
    }


def brief(doc):
    """List item: no file bytes, no full text."""
    c = doc.classification
    return {
        "id": str(doc.id),
        "filename": doc.original_filename,
        "file_type": doc.file_ext.upper(),
        "size": doc.size_bytes,
        "status": doc.status.value,
        "doc_type": c.doc_type if c else None,
        "doc_type_label": TYPE_LABELS.get(c.doc_type) if c else None,
        "confidence": c.confidence if c else None,
        "reviewed": doc.reviewed_at is not None,
        "uploaded_at": _iso(doc.uploaded_at),
    }


def detail(doc):
    data = brief(doc)
    data.update({
        "mime_type": doc.mime_type,
        "sha256": doc.sha256,
        "error": doc.error_message,
        "text": doc.extracted_text,
        "classification": classification_dict(doc),
        "fields": [f.to_dict() for f in doc.fields],
        "summary": doc.summary.to_dict() if doc.summary else None,
        "reviewed_at": _iso(doc.reviewed_at),
        "file_url": f"/api/documents/{doc.id}/file",
    })
    return data


def get_own_document(doc_id, *options):
    try:
        key = uuid.UUID(str(doc_id))
    except ValueError:
        return None
    q = Document.query.filter_by(id=key, user_id=g.user.id)
    if options:
        q = q.options(*options)
    return q.first()


def not_found():
    return error("Document not found.", 404)


# ---------------------------------------------------------------------------
# US2 upload (+ US3 classification + US4 extraction)
# ---------------------------------------------------------------------------
@bp.post("")
@login_required_api
def upload():
    file = request.files.get("file")
    if file is None:
        return error("No file part in the request.", 400)
    if not file.filename:
        return error("No file selected.", 400)

    ext = file_extension(file.filename)
    if ext not in ALLOWED_TYPES:
        return error("Unsupported file format. Please upload a PDF or DOCX file.", 400)

    data = file.read()
    if not data:
        return error("The file is empty.", 400)
    if len(data) > current_app.config["MAX_FILE_SIZE"]:
        mb = current_app.config["MAX_FILE_SIZE"] // (1024 * 1024)
        return error(f"File exceeds the maximum size of {mb} MB.", 413)
    if not has_valid_signature(data, ext):
        return error(f"Unsupported file format: the content is not a real {ext.upper()} file.", 400)

    doc = Document(
        user_id=g.user.id,
        original_filename=file.filename[:255],
        mime_type=ALLOWED_TYPES[ext],
        file_ext=ext,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        file_data=data,
        status=DocumentStatus.uploaded,
    )
    db.session.add(doc)
    db.session.commit()  # the upload itself is safe even if processing breaks

    try:
        process_document(doc)
        db.session.commit()
    except Exception:
        current_app.logger.exception("Processing failed for document %s", doc.id)
        db.session.rollback()
        doc.status = DocumentStatus.failed
        doc.error_message = "The document was uploaded but could not be processed."
        db.session.commit()

    c = doc.classification
    if doc.status == DocumentStatus.failed:
        message = f"Uploaded “{doc.original_filename}”, but it could not be read. {doc.error_message}"
    elif c is not None and c.doc_type == FALLBACK_TYPE:
        message = f"Uploaded “{doc.original_filename}”. The document type could not be determined."
    else:
        message = (f"Uploaded “{doc.original_filename}”. Classified as "
                   f"{TYPE_LABELS[c.doc_type]} ({round(c.confidence * 100)}%).")

    body = detail(doc)
    body["message"] = message
    return jsonify(body), 201


# ---------------------------------------------------------------------------
# My documents
# ---------------------------------------------------------------------------
@bp.get("")
@login_required_api
def list_documents():
    q = (Document.query
         .filter_by(user_id=g.user.id)
         .options(joinedload(Document.classification))
         .order_by(Document.uploaded_at.desc(), Document.id))
    term = (request.args.get("q") or "").strip()
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = "%" + escaped + "%"
        q = q.filter(or_(Document.original_filename.ilike(like), Document.extracted_text.ilike(like)))
    return jsonify([brief(d) for d in q.all()]), 200


@bp.get("/<doc_id>")
@login_required_api
def get_document(doc_id):
    doc = get_own_document(doc_id, undefer(Document.extracted_text))
    if doc is None:
        return not_found()
    return jsonify(detail(doc)), 200


@bp.delete("/<doc_id>")
@login_required_api
def delete_document(doc_id):
    doc = get_own_document(doc_id)
    if doc is None:
        return not_found()
    db.session.delete(doc)
    db.session.commit()
    return jsonify({"deleted": str(doc_id)}), 200


@bp.get("/<doc_id>/file")
@login_required_hybrid
def get_file(doc_id):
    doc = get_own_document(doc_id, undefer(Document.file_data))
    if doc is None:
        return not_found()
    resp = send_file(io.BytesIO(doc.file_data), mimetype=doc.mime_type,
                     download_name=doc.original_filename, as_attachment=False, max_age=0)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------------------
# US4 review & correction
# ---------------------------------------------------------------------------
@bp.patch("/<doc_id>/fields")
@login_required_api
def update_fields(doc_id):
    doc = get_own_document(doc_id, undefer(Document.extracted_text))
    if doc is None:
        return not_found()
    if doc.classification is None or doc.status == DocumentStatus.failed:
        return error("Fields can only be edited after the document has been classified and read.", 409)

    payload = request.get_json(silent=True)
    updates = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(updates, dict) or not updates:
        return error('Send {"fields": {"field_name": "value", ...}}.', 400)

    by_name = {f.field_name: f for f in doc.fields}
    unknown = [name for name in updates if name not in by_name]
    if unknown:
        return error(f"Unknown field(s) for this document: {', '.join(sorted(unknown))}.", 400)

    clean = {}
    for name, value in updates.items():  # validate everything before changing anything
        if value is not None and not isinstance(value, str):
            return error(f"Value for {name} must be text or null.", 400)
        value = (value or "").strip()
        if len(value) > MAX_FIELD_VALUE:
            return error(f"Value for {name} is too long (max {MAX_FIELD_VALUE} characters).", 400)
        clean[name] = value

    for name, value in clean.items():
        field = by_name[name]
        if value:
            field.value, field.state = value, FieldState.corrected
        else:  # the user confirms the field is not in the document
            field.value, field.state = None, FieldState.missing
    db.session.commit()
    return jsonify(detail(doc)), 200


@bp.post("/<doc_id>/review")
@login_required_api
def mark_reviewed(doc_id):
    doc = get_own_document(doc_id, undefer(Document.extracted_text))
    if doc is None:
        return not_found()
    if doc.status == DocumentStatus.failed:
        return error("This document could not be read, so there is nothing to review.", 409)
    doc.reviewed_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(detail(doc)), 200


# ---------------------------------------------------------------------------
# US5 summary
# ---------------------------------------------------------------------------
@bp.post("/<doc_id>/summary")
@login_required_api
def create_summary(doc_id):
    doc = get_own_document(doc_id, undefer(Document.extracted_text))
    if doc is None:
        return not_found()
    if doc.status == DocumentStatus.failed or not (doc.extracted_text or "").strip():
        return error("This document has no extracted text, so it can't be summarized. "
                     "Upload a text-based PDF or DOCX.", 422)
    summary = summarize_document(doc)
    if not summary.bullets:
        db.session.rollback()
        return error("The document text is too short to summarize.", 422)
    db.session.commit()
    return jsonify(summary.to_dict()), 201


@bp.get("/<doc_id>/summary")
@login_required_api
def get_summary(doc_id):
    doc = get_own_document(doc_id)
    if doc is None:
        return not_found()
    if doc.summary is None:
        return error("No summary yet. Generate one first.", 404)
    return jsonify(doc.summary.to_dict()), 200
