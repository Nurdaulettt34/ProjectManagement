"""Request helpers shared by the test modules."""
import io

from uniflow.extensions import db

from .factories import make_docx, make_pdf

PASSWORD = "correct-horse"
STUDENT_EMAIL = "student@stu.sdu.edu.kz"


def last_code(app, email):
    """The latest verification code emailed to `email` (memory mail backend)."""
    email = email.strip().lower()
    for message in reversed(app.extensions.get("mail_outbox", [])):
        if message["to"] == email:
            return message["code"]
    raise AssertionError(f"No email was sent to {email}")


def register(client, email=STUDENT_EMAIL, password=PASSWORD, full_name="Test Student",
             role="student", verify=True, onboard=True):
    """POST /api/register and return its response. By default the account is
    then confirmed with the emailed code (which logs the user in) and the
    welcome tour is marked as done, so the client is ready to use the app."""
    resp = client.post("/api/register", json={
        "full_name": full_name, "email": email, "password": password, "role": role,
    })
    if verify and resp.status_code == 201:
        code = last_code(client.application, email)
        confirmed = client.post("/api/verify-email", json={"email": email, "code": code})
        assert confirmed.status_code == 200, confirmed.get_json()
        if onboard:
            assert client.post("/api/onboarding/complete").status_code == 200
    return resp


def upload(client, data, filename):
    return client.post(
        "/api/documents",
        data={"file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def upload_pdf(client, lines=None, filename="document.pdf"):
    return upload(client, make_pdf(lines) if lines else make_pdf(), filename)


def upload_docx(client, lines=None, filename="document.docx"):
    return upload(client, make_docx(lines) if lines else make_docx(), filename)


def count(app, model):
    with app.app_context():
        return db.session.query(model).count()
