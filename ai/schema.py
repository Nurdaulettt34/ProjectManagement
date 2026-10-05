"""Shared vocabulary of the AI layer: document types and the fields that are
extracted for each type. Used by the providers, the database constraints and
the API, so there is exactly one source of truth."""

DOC_TYPES = (
    "certificate",
    "application_form",
    "request",
    "transcript",
    "id_document",
    "internal_form",
    "other",
)

FALLBACK_TYPE = "other"

FIELD_STATES = ("ok", "missing", "unclear", "corrected")

# Which fields are extracted for which document type (US4).
FIELD_SCHEMAS = {
    "certificate": ["full_name", "issuer", "issue_date", "document_number", "purpose"],
    "application_form": ["full_name", "student_id", "faculty", "request_subject", "date"],
    "request": ["full_name", "addressee", "request_subject", "date"],
    "transcript": ["full_name", "student_id", "program", "gpa", "issue_date"],
    "id_document": ["full_name", "document_number", "date_of_birth", "issue_date", "expiry_date"],
    "internal_form": ["department", "form_number", "date", "approved_by"],
    "other": [],
}

DATE_FIELDS = {"issue_date", "date", "date_of_birth", "expiry_date"}

SUMMARY_MIN_BULLETS = 3
SUMMARY_MAX_BULLETS = 7
