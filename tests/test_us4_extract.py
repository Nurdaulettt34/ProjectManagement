"""US4 Extract Document Information — test scripts, G/W/T, rules."""
import hashlib

import pytest
from uuid import UUID
from sqlalchemy.exc import IntegrityError

from ai import FIELD_SCHEMAS
from ai import service as ai_service
from ai.llm import AIProviderError
from uniflow.extensions import db
from uniflow.models import Document, ExtractedField, FieldState
from uniflow.services import PipelineError, extract_fields

from .factories import APPLICATION_LINES, CERT_LINES, blurred_certificate_lines, make_docx, make_pdf
from .helpers import register, upload


def fields_by_name(body):
    return {f["name"]: f for f in body["fields"]}


def upload_cert(client, lines=CERT_LINES):
    resp = upload(client, make_pdf(lines), "cert.pdf")
    assert resp.status_code == 201
    return resp.get_json()


# --- Test scripts -----------------------------------------------------------

def test_us4_clear_document_required_information_extracted(auth_client):
    f = fields_by_name(upload_cert(auth_client))
    assert f["full_name"] == {"name": "full_name", "value": "Aigerim Sadykova", "state": "ok"}
    assert f["issuer"]["value"] == "Registrar's Office, Satbayev University"
    assert f["issue_date"]["value"] == "15.09.2026"
    assert f["document_number"]["value"] == "CERT-2026-0415"
    assert f["purpose"]["value"] == "for submission to the military registration office"
    assert all(x["state"] == "ok" for x in f.values())


def test_us4_valid_certificate_relevant_fields_displayed(auth_client):
    body = upload_cert(auth_client)
    detail = auth_client.get(f"/api/documents/{body['id']}").get_json()
    assert [x["name"] for x in detail["fields"]] == FIELD_SCHEMAS["certificate"]


def test_us4_blurred_document_unclear_information_marked(auth_client):
    f = fields_by_name(upload_cert(auth_client, blurred_certificate_lines()))
    assert f["issue_date"]["state"] == "unclear"
    assert f["document_number"]["state"] == "unclear"
    assert f["full_name"]["state"] == "ok"


def test_us4_missing_field_remains_empty_instead_of_invented(auth_client, app):
    body = upload_cert(auth_client, blurred_certificate_lines())  # no "Purpose" line
    f = fields_by_name(body)
    assert f["purpose"] == {"name": "purpose", "value": None, "state": "missing"}
    with app.app_context():
        row = ExtractedField.query.filter_by(document_id=UUID(body["id"]), field_name="purpose").one()
        assert row.value is None and row.state == FieldState.missing


def test_us4_original_document_unchanged_after_extraction_and_correction(auth_client, app):
    raw = make_pdf(CERT_LINES)
    original_hash = hashlib.sha256(raw).hexdigest()
    doc_id = upload(auth_client, raw, "cert.pdf").get_json()["id"]
    auth_client.patch(f"/api/documents/{doc_id}/fields", json={"fields": {"purpose": "Scholarship office"}})
    auth_client.post(f"/api/documents/{doc_id}/review")
    with app.app_context():
        doc = db.session.get(Document, UUID(doc_id))
        assert hashlib.sha256(bytes(doc.file_data)).hexdigest() == original_hash == doc.sha256
    assert hashlib.sha256(auth_client.get(f"/api/documents/{doc_id}/file").data).hexdigest() == original_hash


# --- Given/When/Then --------------------------------------------------------

def test_us4_gwt_information_successfully_extracted(auth_client):
    # Given a supported document has been uploaded and its type identified
    body = upload(auth_client, make_docx(APPLICATION_LINES), "leave.docx").get_json()
    assert body["classification"]["type"] == "application_form"
    # When the system processes it; Then important info is extracted and displayed
    f = fields_by_name(auth_client.get(f"/api/documents/{body['id']}").get_json())
    assert f["full_name"]["value"] == "Daniyar Bekov"
    assert f["student_id"]["value"] == "220103456"
    assert f["faculty"]["value"] == "Information Technology"
    assert f["date"]["value"] == "01.10.2026"


def test_us4_gwt_unclear_or_missing_info_marked_and_user_reviews(auth_client):
    # Given a document with unclear or missing information
    body = upload_cert(auth_client, blurred_certificate_lines())
    # When it is processed, Then the unavailable information is marked ...
    states = {f["name"]: f["state"] for f in body["fields"]}
    assert states["issue_date"] == "unclear" and states["purpose"] == "missing"
    # ... and the user can review and correct it
    resp = auth_client.patch(f"/api/documents/{body['id']}/fields",
                             json={"fields": {"issue_date": "15.09.2026", "purpose": "Scholarship office"}})
    assert resp.status_code == 200
    f = fields_by_name(resp.get_json())
    assert f["issue_date"] == {"name": "issue_date", "value": "15.09.2026", "state": "corrected"}
    assert f["purpose"]["state"] == "corrected"
    reviewed = auth_client.post(f"/api/documents/{body['id']}/review").get_json()
    assert reviewed["reviewed"] is True and reviewed["reviewed_at"]


# --- Rule-oriented ----------------------------------------------------------

def test_us4_rule_extraction_starts_after_classification(auth_client, app):
    doc_id = upload_cert(auth_client)["id"]
    with app.app_context():
        doc = db.session.get(Document, UUID(doc_id))
        db.session.delete(doc.classification)
        db.session.flush()
        db.session.refresh(doc)
        with pytest.raises(PipelineError):
            extract_fields(doc)
        db.session.rollback()


def test_us4_rule_field_set_depends_on_document_type(auth_client):
    cert = upload_cert(auth_client)
    app_form = upload(auth_client, make_docx(APPLICATION_LINES), "app.docx").get_json()
    assert [f["name"] for f in cert["fields"]] == FIELD_SCHEMAS["certificate"]
    assert [f["name"] for f in app_form["fields"]] == FIELD_SCHEMAS["application_form"]


def test_us4_rule_extracted_information_displayed_clearly(auth_client):
    body = upload_cert(auth_client)
    for f in auth_client.get(f"/api/documents/{body['id']}").get_json()["fields"]:
        assert set(f) == {"name", "value", "state"}
        assert f["state"] in ("ok", "missing", "unclear", "corrected")


def test_us4_rule_missing_information_never_invented_db_constraint(auth_client, app):
    doc_id = upload_cert(auth_client)["id"]
    with app.app_context():
        db.session.add(ExtractedField(document_id=UUID(doc_id), field_name="extra", value="made up",
                                      state=FieldState.missing))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_us4_rule_failed_document_has_no_fields_and_cannot_be_edited(auth_client, app):
    body = upload(auth_client, b"%PDF-1.4\nbroken", "bad.pdf").get_json()
    assert body["fields"] == []
    resp = auth_client.patch(f"/api/documents/{body['id']}/fields", json={"fields": {"purpose": "x"}})
    assert resp.status_code == 409
    assert auth_client.post(f"/api/documents/{body['id']}/review").status_code == 409


def test_us4_patch_unknown_field_rejected(auth_client):
    doc_id = upload_cert(auth_client)["id"]
    resp = auth_client.patch(f"/api/documents/{doc_id}/fields", json={"fields": {"salary": "1000"}})
    assert resp.status_code == 400
    assert "salary" in resp.get_json()["error"]


@pytest.mark.parametrize("payload", [{}, {"fields": {}}, {"fields": ["x"]}, {"fields": {"purpose": 5}}])
def test_us4_patch_bad_payload_rejected(auth_client, payload):
    doc_id = upload_cert(auth_client)["id"]
    assert auth_client.patch(f"/api/documents/{doc_id}/fields", json=payload).status_code == 400


def test_us4_patch_empty_value_marks_missing(auth_client):
    doc_id = upload_cert(auth_client)["id"]
    f = fields_by_name(auth_client.patch(f"/api/documents/{doc_id}/fields",
                                         json={"fields": {"purpose": "  "}}).get_json())
    assert f["purpose"] == {"name": "purpose", "value": None, "state": "missing"}


def test_us4_other_user_cannot_edit_fields(client):
    register(client, email="owner@stu.sdu.edu.kz")
    doc_id = upload_cert(client)["id"]
    client.post("/api/logout")
    register(client, email="intruder@stu.sdu.edu.kz")
    resp = client.patch(f"/api/documents/{doc_id}/fields", json={"fields": {"purpose": "hacked"}})
    assert resp.status_code == 404


# --- Optional LLM provider --------------------------------------------------

class FakeExtractLLM:
    def classify(self, text):
        return {"type": "certificate", "confidence": 0.95}

    def extract(self, text, doc_type):
        return {
            "full_name": {"value": "Aigerim Sadykova", "state": "ok"},
            "issuer": {"value": "Harvard University", "state": "ok"},   # not in the text -> invented
            "issue_date": {"value": "15.09.2026", "state": "ok"},
            "document_number": {"value": None, "state": "ok"},          # null -> missing
            "salary": {"value": "1000", "state": "ok"},                 # not in schema -> ignored
        }

    def summarize(self, text):
        raise AIProviderError("not used")


def test_us4_llm_invented_values_are_discarded(auth_client, monkeypatch):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeExtractLLM())
    f = fields_by_name(upload_cert(auth_client))
    assert f["full_name"]["value"] == "Aigerim Sadykova"
    assert f["issuer"] == {"name": "issuer", "value": None, "state": "missing"}
    assert f["document_number"]["state"] == "missing"
    assert f["purpose"]["state"] == "missing"   # LLM did not return it
    assert "salary" not in f
