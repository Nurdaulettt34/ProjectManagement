"""US2 Upload Document — test scripts, G/W/T scenarios, rules."""
import hashlib
from uuid import UUID

import pytest

from uniflow.extensions import db
from uniflow.models import Document, DocumentClassification

from .factories import CERT_LINES, make_docx, make_pdf, make_zip_not_docx
from .helpers import count, upload


# --- Test scripts -----------------------------------------------------------

def test_us2_valid_pdf_uploaded_appears_in_my_documents(auth_client):
    resp = upload(auth_client, make_pdf(CERT_LINES), "enrollment.pdf")
    assert resp.status_code == 201
    doc_id = resp.get_json()["id"]
    listing = auth_client.get("/api/documents").get_json()
    assert [d["id"] for d in listing] == [doc_id]
    assert listing[0]["filename"] == "enrollment.pdf"


def test_us2_valid_docx_accepted(auth_client, app):
    resp = upload(auth_client, make_docx(), "form.docx")
    assert resp.status_code == 201
    assert resp.get_json()["file_type"] == "DOCX"
    assert count(app, Document) == 1


@pytest.mark.parametrize("filename,data", [
    ("photo.jpg", b"\xff\xd8\xff\xe0fakejpeg"),
    ("notes.txt", b"plain text file"),
    ("virus.exe", b"MZ\x90\x00"),
    ("noextension", b"%PDF-1.4"),
    ("old.doc", b"\xd0\xcf\x11\xe0"),
])
def test_us2_unsupported_file_format_rejected(auth_client, app, filename, data):
    resp = upload(auth_client, data, filename)
    assert resp.status_code == 400
    assert "Unsupported" in resp.get_json()["error"]
    assert count(app, Document) == 0


@pytest.mark.parametrize("filename", ["empty.pdf", "empty.docx"])
def test_us2_empty_file_rejected(auth_client, app, filename):
    resp = upload(auth_client, b"", filename)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "The file is empty."
    assert count(app, Document) == 0


# --- Given/When/Then --------------------------------------------------------

def test_us2_gwt_successful_document_upload(auth_client):
    # Given the user is logged in and is on the upload page
    assert auth_client.get("/app").status_code == 200
    # When they select a supported document and click Upload
    resp = upload(auth_client, make_pdf(CERT_LINES), "certificate.pdf")
    # Then the document is uploaded and appears in the user's documents
    assert resp.status_code == 201
    assert "Uploaded" in resp.get_json()["message"]
    assert auth_client.get("/api/documents").get_json()[0]["filename"] == "certificate.pdf"


def test_us2_gwt_unsupported_file(auth_client, app):
    # Given the user is on the upload page; When they select an unsupported type
    resp = upload(auth_client, b"GIF89a....", "scan.gif")
    # Then the system displays an error and does not upload the file
    assert resp.status_code == 400
    assert resp.get_json()["error"]
    assert count(app, Document) == 0
    # ...and nothing is classified (no digital record exists to type as "Other")
    assert count(app, DocumentClassification) == 0


# --- Rule-oriented ----------------------------------------------------------

def test_us2_rule_file_content_must_match_pdf_signature(auth_client, app):
    resp = upload(auth_client, b"just text renamed to pdf", "fake.pdf")
    assert resp.status_code == 400
    assert "not a real PDF" in resp.get_json()["error"]
    assert count(app, Document) == 0


@pytest.mark.parametrize("data", [make_pdf(), make_zip_not_docx(), b"PK\x03\x04broken zip"])
def test_us2_rule_file_content_must_match_docx_signature(auth_client, app, data):
    resp = upload(auth_client, data, "fake.docx")
    assert resp.status_code == 400
    assert count(app, Document) == 0


def test_us2_rule_user_must_be_logged_in(client, app):
    resp = upload(client, make_pdf(), "doc.pdf")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Not authenticated."}
    assert count(app, Document) == 0


def test_us2_rule_system_confirms_successful_upload(auth_client):
    data = upload(auth_client, make_docx(), "ok.docx").get_json()
    assert data["message"].startswith("Uploaded “ok.docx”")
    assert data["id"]


def test_us2_rule_file_size_limit(auth_client, app):
    old = app.config["MAX_FILE_SIZE"]
    app.config["MAX_FILE_SIZE"] = 1024
    try:
        resp = upload(auth_client, make_pdf(["x" * 50] * 40), "big.pdf")
        assert len(make_pdf(["x" * 50] * 40)) > 1024
        assert resp.status_code == 413
        assert "maximum size" in resp.get_json()["error"]
    finally:
        app.config["MAX_FILE_SIZE"] = old
    assert count(app, Document) == 0


def test_us2_original_stored_in_database_with_sha256(auth_client, app):
    raw = make_pdf(CERT_LINES)
    doc_id = upload(auth_client, raw, "cert.pdf").get_json()["id"]
    with app.app_context():
        doc = db.session.get(Document, UUID(doc_id))
        assert bytes(doc.file_data) == raw
        assert doc.sha256 == hashlib.sha256(raw).hexdigest()
        assert doc.size_bytes == len(raw)
        assert doc.mime_type == "application/pdf"


def test_us2_original_file_download_returns_same_bytes(auth_client):
    raw = make_docx()
    doc_id = upload(auth_client, raw, "orig.docx").get_json()["id"]
    resp = auth_client.get(f"/api/documents/{doc_id}/file")
    assert resp.status_code == 200
    assert resp.data == raw


def test_us2_file_link_redirects_browser_to_login(client, auth_client):
    doc_id = upload(auth_client, make_pdf(), "a.pdf").get_json()["id"]
    auth_client.post("/api/logout")
    nav = client.get(f"/api/documents/{doc_id}/file", headers={"Accept": "text/html"})
    assert nav.status_code == 302 and "/login" in nav.headers["Location"]
    api = client.get(f"/api/documents/{doc_id}/file", headers={"Accept": "application/json"})
    assert api.status_code == 401


def test_us2_list_does_not_return_full_text(auth_client):
    upload(auth_client, make_pdf(CERT_LINES), "cert.pdf")
    item = auth_client.get("/api/documents").get_json()[0]
    assert "text" not in item and "file_data" not in item
    assert {"id", "filename", "status", "doc_type", "confidence"} <= set(item)


def test_us2_list_search_by_name_and_text(auth_client):
    upload(auth_client, make_pdf(CERT_LINES), "enrollment.pdf")
    upload(auth_client, make_docx(), "other.docx")
    assert len(auth_client.get("/api/documents?q=enroll").get_json()) == 1
    assert len(auth_client.get("/api/documents?q=Satbayev").get_json()) == 1
    assert len(auth_client.get("/api/documents?q=100%25").get_json()) == 0
