"""US5 Summarize University Document — scenarios and rules."""
import re

import pytest

from ai import service as ai_service
from ai.llm import AIProviderError
from uniflow.models import AIMethod, DocumentSummary

from .factories import REGULATION_LINES, make_blank_pdf, make_docx
from .helpers import count, register, upload


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


@pytest.fixture
def regulation(auth_client):
    body = upload(auth_client, make_docx(REGULATION_LINES), "transfer-rules.docx").get_json()
    assert body["status"] == "processed"
    return body


def test_us5_summary_has_3_to_7_bullets(auth_client, regulation):
    resp = auth_client.post(f"/api/documents/{regulation['id']}/summary")
    assert resp.status_code == 201
    bullets = resp.get_json()["bullets"]
    assert 3 <= len(bullets) <= 7
    assert all(isinstance(b, str) and b for b in bullets)


def test_us5_summary_based_only_on_document_text(auth_client, regulation):
    text = norm(auth_client.get(f"/api/documents/{regulation['id']}").get_json()["text"])
    bullets = auth_client.post(f"/api/documents/{regulation['id']}/summary").get_json()["bullets"]
    for b in bullets:
        assert norm(b.rstrip("…")) in text  # every bullet comes from the document


def test_us5_summary_covers_deadlines_requirements_documents(auth_client, regulation):
    joined = " ".join(auth_client.post(f"/api/documents/{regulation['id']}/summary").get_json()["bullets"])
    assert "25 August 2026" in joined            # deadline
    assert "copy of the passport" in joined      # required documents
    assert "must" in joined                      # requirement


def test_us5_summary_requires_extracted_text(auth_client):
    body = upload(auth_client, make_blank_pdf(), "scan.pdf").get_json()
    resp = auth_client.post(f"/api/documents/{body['id']}/summary")
    assert resp.status_code == 422
    assert "no extracted text" in resp.get_json()["error"]


def test_us5_summary_stored_and_retrievable(auth_client, app, regulation):
    created = auth_client.post(f"/api/documents/{regulation['id']}/summary").get_json()
    got = auth_client.get(f"/api/documents/{regulation['id']}/summary")
    assert got.status_code == 200
    assert got.get_json()["bullets"] == created["bullets"]
    assert got.get_json()["method"] == "rules"
    assert auth_client.get(f"/api/documents/{regulation['id']}").get_json()["summary"]["bullets"] == created["bullets"]
    with app.app_context():
        row = DocumentSummary.query.one()
        assert row.method == AIMethod.rules and row.bullets == created["bullets"]


def test_us5_regenerating_replaces_summary(auth_client, app, regulation):
    auth_client.post(f"/api/documents/{regulation['id']}/summary")
    auth_client.post(f"/api/documents/{regulation['id']}/summary")
    assert count(app, DocumentSummary) == 1


def test_us5_get_summary_before_generation(auth_client, regulation):
    resp = auth_client.get(f"/api/documents/{regulation['id']}/summary")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "No summary yet. Generate one first."


def test_us5_other_user_cannot_summarize(client):
    register(client, email="owner@stu.sdu.edu.kz")
    doc_id = upload(client, make_docx(REGULATION_LINES), "rules.docx").get_json()["id"]
    client.post("/api/logout")
    register(client, email="intruder@stu.sdu.edu.kz")
    assert client.post(f"/api/documents/{doc_id}/summary").status_code == 404
    assert client.get(f"/api/documents/{doc_id}/summary").status_code == 404


def test_us5_summary_requires_login(client):
    assert client.post("/api/documents/00000000-0000-0000-0000-000000000000/summary").status_code == 401


class FakeSummaryLLM:
    def __init__(self, bullets):
        self.bullets = bullets

    def classify(self, text):
        raise AIProviderError("use rules")

    def extract(self, text, doc_type):
        raise AIProviderError("use rules")

    def summarize(self, text):
        return self.bullets


def test_us5_llm_bullets_with_invented_numbers_dropped(auth_client, monkeypatch, regulation):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeSummaryLLM([
        "Submit the application by 25 August 2026.",
        "Bring a copy of your passport and two photos.",
        "The fee is 50000 tenge.",                     # not in the document
    ]))
    body = auth_client.post(f"/api/documents/{regulation['id']}/summary").get_json()
    assert body["method"] == "llm"
    assert body["bullets"] == ["Submit the application by 25 August 2026.",
                               "Bring a copy of your passport and two photos."]


def test_us5_llm_failure_falls_back_to_rules(auth_client, monkeypatch, regulation):
    monkeypatch.setattr(ai_service, "get_llm_provider", lambda: FakeSummaryLLM("not a list"))
    body = auth_client.post(f"/api/documents/{regulation['id']}/summary").get_json()
    assert body["method"] == "rules"
    assert 3 <= len(body["bullets"]) <= 7
