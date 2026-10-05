"""The 21 Sprint 1 tests, adapted to PostgreSQL and the new REST API
(/upload -> POST /api/documents, /records -> /api/documents, statuses in
lower case, registration with full name and role). Names are unchanged."""

from uniflow.models import Document

from .factories import make_docx, make_pdf
from .helpers import count, register, upload, upload_docx, upload_pdf


# --- Auth: registration, login, logout, route protection -------------------

def test_login_page_loads(client):
    assert client.get("/login").status_code == 200


def test_register_page_loads(client):
    assert client.get("/register").status_code == 200


def test_index_redirects_to_login_when_logged_out(client):
    resp = client.get("/app", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_upload_requires_login(client):
    resp = upload(client, make_pdf(), "application.pdf")
    assert resp.status_code == 401


def test_register_creates_account_and_logs_in(client):
    resp = register(client, email="new.student@stu.sdu.edu.kz", password="supersecret1")
    assert resp.status_code == 201
    assert client.get("/app").status_code == 200


def test_register_rejects_invalid_email(client):
    assert register(client, email="not-an-email", password="supersecret1").status_code == 400


def test_register_rejects_short_password(client):
    assert register(client, email="student2@stu.sdu.edu.kz", password="short").status_code == 400


def test_register_rejects_duplicate_email(client):
    register(client, email="dup@stu.sdu.edu.kz", password="supersecret1")
    resp = register(client, email="dup@stu.sdu.edu.kz", password="anotherpass1")
    assert resp.status_code == 409


def test_login_with_correct_credentials(client):
    register(client, email="login.test@stu.sdu.edu.kz", password="supersecret1")
    client.post("/api/logout")
    resp = client.post("/api/login", json={"email": "login.test@stu.sdu.edu.kz", "password": "supersecret1"})
    assert resp.status_code == 200


def test_login_with_wrong_password_fails(client):
    register(client, email="login.test2@stu.sdu.edu.kz", password="supersecret1")
    client.post("/api/logout")
    resp = client.post("/api/login", json={"email": "login.test2@stu.sdu.edu.kz", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_logout_then_index_requires_login(auth_client):
    auth_client.post("/api/logout")
    assert auth_client.get("/app", follow_redirects=False).status_code == 302


# --- Upload / extraction ----------------------------------------------------

def test_index_page_loads(auth_client):
    assert auth_client.get("/app").status_code == 200


def test_upload_valid_pdf_passes(auth_client):
    resp = upload_pdf(auth_client, filename="application.pdf")
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["status"] == "processed"
    assert "test PDF" in data["text"]


def test_upload_valid_docx_passes(auth_client):
    resp = upload_docx(auth_client, filename="certificate.docx")
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["status"] == "processed"
    assert "test DOCX" in data["text"]


def test_upload_unsupported_image_fails(auth_client):
    resp = upload(auth_client, b"\xff\xd8\xff\xe0fakejpeg", "photo.jpg")
    assert resp.status_code == 400
    assert "Unsupported" in resp.get_json()["error"]


def test_upload_unsupported_text_fails(auth_client):
    resp = upload(auth_client, b"plain text", "something.txt")
    assert resp.status_code == 400
    assert "Unsupported" in resp.get_json()["error"]


def test_upload_empty_file_fails(auth_client):
    resp = upload(auth_client, b"", "empty.pdf")
    assert resp.status_code == 400
    assert "empty" in resp.get_json()["error"].lower()


def test_upload_corrupted_pdf_reports_failed_status(auth_client):
    # Has the PDF signature (so it passes validation) but is broken inside:
    # it is stored with status "failed" instead of being rejected.
    resp = upload(auth_client, b"%PDF-1.4\nthis is not a real pdf file", "broken.pdf")
    data = resp.get_json()
    assert resp.status_code == 201
    assert data["status"] == "failed"
    assert data["error"]


def test_records_list_reflects_uploads(auth_client):
    upload(auth_client, make_pdf(), "one.pdf")
    upload(auth_client, make_docx(), "two.docx")
    records = auth_client.get("/api/documents").get_json()
    assert len(records) == 2


def test_mark_reviewed_and_delete(auth_client, app):
    record_id = upload_pdf(auth_client, filename="reviewme.pdf").get_json()["id"]

    review_resp = auth_client.post(f"/api/documents/{record_id}/review")
    assert review_resp.status_code == 200
    assert review_resp.get_json()["reviewed"] is True

    assert auth_client.delete(f"/api/documents/{record_id}").status_code == 200
    records = auth_client.get("/api/documents").get_json()
    assert all(r["id"] != record_id for r in records)
    assert count(app, Document) == 0  # really gone from the database


# --- Per-user isolation -----------------------------------------------------

def test_records_are_isolated_per_user(client):
    register(client, email="userA@stu.sdu.edu.kz", password="passwordA1")
    record_id = upload_pdf(client, filename="userA-doc.pdf").get_json()["id"]
    client.post("/api/logout")

    register(client, email="userB@stu.sdu.edu.kz", password="passwordB1")
    assert client.get("/api/documents").get_json() == []

    assert client.get(f"/api/documents/{record_id}/file").status_code == 404
    assert client.get(f"/api/documents/{record_id}").status_code == 404
    assert client.post(f"/api/documents/{record_id}/review").status_code == 404
    assert client.delete(f"/api/documents/{record_id}").status_code == 404
