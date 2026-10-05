"""US3 Classify Document — test scripts, G/W/T scenarios, rules."""
import hashlib

import pytest
from uuid import UUID
from sqlalchemy.exc import IntegrityError

import ai
from ai import service as ai_service
from ai.llm import AIProviderError
from uniflow.extensions import db
from uniflow.models import AIMethod, Document, DocumentClassification

from .factories import (
    APPLICATION_LINES,
    CERT_LINES,
    KZ_CERT_LINES,
    LOW_CONFIDENCE_LINES,
    RU_CERT_LINES,
    UNIDENTIFIABLE_LINES,
    make_blank_pdf,
    make_docx,
    make_pdf,
)
from .helpers import count, upload


def classification_of(resp):
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["classification"]


# --- Test scripts -----------------------------------------------------------

def test_us3_uploaded_certificate_identified_as_certificate(auth_client):
    c = classification_of(upload(auth_client, make_pdf(CERT_LINES), "cert.pdf"))
    assert c["type"] == "certificate"
    assert c["confidence"] >= 0.5
    assert c["method"] == "rules"


def test_us3_uploaded_application_form_identified(auth_client):
    c = classification_of(upload(auth_client, make_docx(APPLICATION_LINES), "app.docx"))
    assert c["type"] == "application_form"


@pytest.mark.parametrize("lines", [RU_CERT_LINES, KZ_CERT_LINES], ids=["ru", "kz"])
def test_us3_russian_and_kazakh_certificates_identified(auth_client, lines):
    c = classification_of(upload(auth_client, make_docx(lines), "spravka.docx"))
    assert c["type"] == "certificate"


@pytest.mark.parametrize("data,filename", [
    (make_blank_pdf(), "scan.pdf"),                       # valid PDF, no text
    (b"%PDF-1.4\n\x00\x01 garbage", "damaged.pdf"),        # broken inside
], ids=["image-only", "damaged"])
def test_us3_unreadable_document_classification_failure_message(auth_client, data, filename):
    body = upload(auth_client, data, filename).get_json()
    assert body["status"] == "failed"
    assert body["classification"]["type"] == "other"
    assert body["classification"]["confidence"] == 0.0
    assert body["classification"]["message"].startswith("Classification failed")
    assert body["fields"] == []


def test_us3_unsupported_file_classification_not_started(auth_client, app):
    resp = upload(auth_client, b"plain text", "notes.txt")
    assert resp.status_code == 400
    assert count(app, DocumentClassification) == 0


def test_us3_original_document_unchanged_after_classification(auth_client, app):
    raw = make_pdf(CERT_LINES)
    before = hashlib.sha256(raw).hexdigest()
    doc_id = upload(auth_client, raw, "cert.pdf").get_json()["id"]
    with app.app_context():
        doc = db.session.get(Document, UUID(doc_id))
        assert doc.classification is not None
        assert hashlib.sha256(bytes(doc.file_data)).hexdigest() == before == doc.sha256


# --- Given/When/Then --------------------------------------------------------

def test_us3_gwt_document_successfully_classified(auth_client):
    # Given a supported document has been uploaded; When the system processes it
    doc_id = upload(auth_client, make_pdf(CERT_LINES), "cert.pdf").get_json()["id"]
    # Then it identifies the type and displays the result
    detail = auth_client.get(f"/api/documents/{doc_id}").get_json()
    assert detail["classification"]["type"] == "certificate"
    assert detail["classification"]["label"] == "Certificate"
    assert detail["classification"]["message"] is None


def test_us3_gwt_unreadable_document_not_misclassified(auth_client):
    # Given a document has been uploaded; When the system cannot identify its type
    c = classification_of(upload(auth_client, make_docx(UNIDENTIFIABLE_LINES), "lorem.docx"))
    # Then it shows a message and does not assign an incorrect category
    assert c["type"] == "other"
    assert "could not determine" in c["message"]


# --- Rule-oriented ----------------------------------------------------------

def test_us3_rule_classification_starts_only_after_upload(auth_client, app):
    assert count(app, DocumentClassification) == 0
    upload(auth_client, make_pdf(CERT_LINES), "cert.pdf")
    assert count(app, DocumentClassification) == 1
    upload(auth_client, b"", "empty.pdf")  # rejected upload -> nothing classified
    assert count(app, DocumentClassification) == 1


@pytest.mark.parametrize("doc_type", ai.DOC_TYPES)
def test_us3_rule_system_classifies_supported_types(auth_client, app, doc_type):
    # every supported type is accepted by the database constraint
    doc_id = upload(auth_client, make_pdf(CERT_LINES), "cert.pdf").get_json()["id"]
    with app.app_context():
        c = DocumentClassification.query.filter_by(document_id=UUID(doc_id)).one()
        c.doc_type = doc_type
        db.session.commit()
        assert DocumentClassification.query.filter_by(document_id=UUID(doc_id)).one().doc_type == doc_type


def test_us3_rule_database_rejects_unknown_type(auth_client, app):
    doc_id = upload(auth_client, make_pdf(CERT_LINES), "cert.pdf").get_json()["id"]
    with app.app_context():
        c = DocumentClassification.query.filter_by(document_id=UUID(doc_id)).one()
        c.doc_type = "diploma"
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_us3_rule_result_displayed_to_user_in_list(auth_client):
    upload(auth_client, make_pdf(CERT_LINES), "cert.pdf")
    item = auth_client.get("/api/documents").get_json()[0]
    assert item["doc_type"] == "certificate"
    assert item["doc_type_label"] == "Certificate"
    assert 0 < item["confidence"] <= 1


def test_us3_rule_low_confidence_falls_back_to_other(auth_client):
    c = classification_of(upload(auth_client, make_docx(LOW_CONFIDENCE_LINES), "note.docx"))
    assert c["type"] == "other"  # one weak "grade" keyword is not enough for "transcript"


def test_us3_classify_interface_returns_type_and_confidence():
    result = ai.classify("\n".join(CERT_LINES))
    assert result["type"] == "certificate"
    assert 0 <= result["confidence"] <= 1


# --- Optional LLM provider --------------------------------------------------

class FakeLLM:
    def __init__(self, answer=None, fail=False):
        self.answer, self.fail = answer, fail

    def classify(self, text):
        if self.fail:
            raise AIProviderError("API down")
        return self.answer

    def extract(self, text, doc_type):
        raise AIProviderError("not used")

    def summarize(self, text):
        raise AIProviderError("not used")


def test_us3_llm_result_used_and_method_llm(auth_client, monkeypatch):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeLLM({"type": "certificate", "confidence": 0.93}))
    c = classification_of(upload(auth_client, make_pdf(CERT_LINES), "cert.pdf"))
    assert (c["type"], c["confidence"], c["method"]) == ("certificate", 0.93, "llm")


def test_us3_llm_error_falls_back_to_rules(auth_client, app, monkeypatch):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeLLM(fail=True))
    doc_id = upload(auth_client, make_pdf(CERT_LINES), "cert.pdf").get_json()["id"]
    with app.app_context():
        c = DocumentClassification.query.filter_by(document_id=UUID(doc_id)).one()
        assert c.method == AIMethod.rules
        assert c.doc_type == "certificate"


@pytest.mark.parametrize("answer", [
    {"type": "diploma", "confidence": 0.9},
    {"type": "certificate", "confidence": "high"},
    {"type": "certificate", "confidence": 7},
    "certificate",
])
def test_us3_llm_invalid_answer_falls_back_to_rules(auth_client, monkeypatch, answer):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeLLM(answer))
    c = classification_of(upload(auth_client, make_pdf(CERT_LINES), "cert.pdf"))
    assert c["method"] == "rules"
    assert c["type"] == "certificate"


def test_us3_llm_low_confidence_reported_as_other(auth_client, monkeypatch):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeLLM({"type": "transcript", "confidence": 0.2}))
    c = classification_of(upload(auth_client, make_pdf(CERT_LINES), "cert.pdf"))
    assert c["type"] == "other"
    assert c["method"] == "llm"
