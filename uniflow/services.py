"""Document processing pipeline: text extraction -> US3 classification ->
US4 field extraction, and US5 summaries. The original file (file_data) is
only ever read here, never written."""
from datetime import datetime, timezone

import ai
from ai.schema import FALLBACK_TYPE

from .files import UnreadableDocument, extract_text
from .models import (
    AIMethod,
    DocumentClassification,
    DocumentStatus,
    DocumentSummary,
    ExtractedField,
    FieldState,
)

OTHER_MESSAGE = ("We could not determine the document type, so it was marked as \"Other\". "
                 "No category was guessed.")
UNREADABLE_MESSAGE = "Classification failed: the document has no readable text."


class PipelineError(Exception):
    """A processing step was called out of order."""


def classify_document(doc):
    """US3. Unreadable documents get type 'other' with confidence 0."""
    try:
        text = extract_text(doc.file_data, doc.file_ext)
    except UnreadableDocument as exc:
        doc.status = DocumentStatus.failed
        doc.error_message = str(exc)
        doc.extracted_text = None
        doc.classification = DocumentClassification(doc_type=FALLBACK_TYPE, confidence=0.0, method=AIMethod.rules)
        return doc.classification

    doc.extracted_text = text
    result, method = ai.run("classify", text)
    doc.classification = DocumentClassification(
        doc_type=result["type"], confidence=result["confidence"], method=AIMethod(method)
    )
    return doc.classification


def extract_fields(doc):
    """US4. Runs only after a classification exists."""
    if doc.classification is None:
        raise PipelineError("Extraction can only run after the document has been classified.")
    if doc.status == DocumentStatus.failed or not doc.extracted_text:
        return []
    fields, _method = ai.run("extract", doc.extracted_text, doc.classification.doc_type)
    doc.fields = [
        ExtractedField(field_name=name, value=item["value"], state=FieldState(item["state"]))
        for name, item in fields.items()
    ]
    return doc.fields


def process_document(doc):
    """Full pipeline right after upload."""
    classify_document(doc)
    extract_fields(doc)
    if doc.status != DocumentStatus.failed:
        doc.status = DocumentStatus.processed
        doc.error_message = None


def summarize_document(doc):
    """US5. Caller has already checked that extracted text exists."""
    bullets, method = ai.run("summarize", doc.extracted_text)
    if doc.summary is None:
        doc.summary = DocumentSummary(bullets=bullets, method=AIMethod(method))
    else:
        doc.summary.bullets = bullets
        doc.summary.method = AIMethod(method)
        doc.summary.created_at = datetime.now(timezone.utc)
    return doc.summary


def classification_message(doc):
    c = doc.classification
    if c is None:
        return None
    if doc.status == DocumentStatus.failed:
        return UNREADABLE_MESSAGE
    if c.doc_type == FALLBACK_TYPE:
        return OTHER_MESSAGE
    return None
