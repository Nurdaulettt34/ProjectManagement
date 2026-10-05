"""US1 additions: SDU email rule for students and email confirmation with a code."""
from datetime import timedelta

import pytest

from uniflow.extensions import db
from uniflow.models import EmailVerification, User
from uniflow.verification import now_utc

from .helpers import PASSWORD, count, last_code, register

STUDENT = {"full_name": "Aigerim Sadykova", "email": "220103001@stu.sdu.edu.kz",
           "password": "supersecret1", "role": "student"}
APPLICANT = {"full_name": "Dana Applicant", "email": "dana.future@gmail.com",
             "password": "supersecret1", "role": "applicant"}


def raw_register(client, data):
    return client.post("/api/register", json=data)


def verify(client, email, code):
    return client.post("/api/verify-email", json={"email": email, "code": code})


def age_code(app, email, **delta):
    """Move the stored code's timestamps into the past."""
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        v = user.verification
        v.sent_at = v.sent_at - timedelta(**delta)
        v.expires_at = v.expires_at - timedelta(**delta)
        db.session.commit()


# --- Students: only SDU university email -----------------------------------

@pytest.mark.parametrize("email", ["220103001@stu.sdu.edu.kz", "a.sadykova@sdu.edu.kz", "Name@STU.SDU.EDU.KZ"])
def test_us1_student_with_sdu_email_accepted(client, app, email):
    resp = raw_register(client, {**STUDENT, "email": email})
    assert resp.status_code == 201
    assert count(app, User) == 1


@pytest.mark.parametrize("email", [
    "student@gmail.com",
    "student@mail.ru",
    "student@notsdu.edu.kz",        # look-alike domain
    "student@sdu.edu.kz.evil.com",  # suffix trick
    "student@sdu.edu",
    "student@sdu.kz",
])
def test_us1_student_with_external_email_rejected(client, app, email):
    resp = raw_register(client, {**STUDENT, "email": email})
    assert resp.status_code == 400
    assert "SDU university email" in resp.get_json()["error"]
    assert count(app, User) == 0
    assert app.extensions["mail_outbox"] == []  # nothing is sent for rejected data


@pytest.mark.parametrize("email", ["dana.future@gmail.com", "dana@mail.ru", "dana@stu.sdu.edu.kz"])
def test_us1_applicant_may_use_any_email(client, app, email):
    assert raw_register(client, {**APPLICANT, "email": email}).status_code == 201
    with app.app_context():
        assert User.query.one().role.value == "applicant"


# --- Email confirmation -------------------------------------------------------

def test_us1_registration_sends_code_and_does_not_log_in(client, app):
    resp = raw_register(client, STUDENT)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["verification_required"] is True and body["email"] == STUDENT["email"]
    assert client.get("/api/me").status_code == 401
    outbox = app.extensions["mail_outbox"]
    assert len(outbox) == 1 and outbox[0]["to"] == STUDENT["email"]
    code = outbox[0]["code"]
    assert len(code) == 6 and code.isdigit() and code in outbox[0]["body"]
    with app.app_context():
        assert User.query.one().email_verified_at is None


def test_us1_code_is_stored_hashed_not_in_plain_text(client, app):
    raw_register(client, STUDENT)
    code = last_code(app, STUDENT["email"])
    with app.app_context():
        v = EmailVerification.query.one()
        assert v.code_hash != code and code not in v.code_hash and len(v.code_hash) == 64


def test_us1_unverified_account_cannot_log_in(client):
    raw_register(client, STUDENT)
    resp = client.post("/api/login", json={"email": STUDENT["email"], "password": STUDENT["password"]})
    assert resp.status_code == 403
    assert resp.get_json()["verification_required"] is True
    assert client.get("/api/me").status_code == 401


def test_us1_unverified_login_with_wrong_password_reveals_nothing(client):
    raw_register(client, STUDENT)
    resp = client.post("/api/login", json={"email": STUDENT["email"], "password": "wrong-password"})
    assert resp.status_code == 401
    assert "verification_required" not in resp.get_json()


def test_us1_correct_code_confirms_email_and_logs_in(client, app):
    raw_register(client, STUDENT)
    resp = verify(client, STUDENT["email"], last_code(app, STUDENT["email"]))
    assert resp.status_code == 200
    assert resp.get_json()["next"] == "/welcome"
    me = client.get("/api/me").get_json()["user"]
    assert me["email_verified"] is True and me["onboarded"] is False
    with app.app_context():
        assert User.query.one().email_verified_at is not None
        assert EmailVerification.query.count() == 0  # used code is deleted


def test_us1_code_with_spaces_is_accepted(client, app):
    raw_register(client, STUDENT)
    code = last_code(app, STUDENT["email"])
    assert verify(client, STUDENT["email"], f" {code[:3]} {code[3:]} ").status_code == 200


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", None])
def test_us1_malformed_code_rejected_without_using_an_attempt(client, app, bad):
    raw_register(client, STUDENT)
    resp = verify(client, STUDENT["email"], bad)
    assert resp.status_code == 400
    with app.app_context():
        assert EmailVerification.query.one().attempts == 0


def test_us1_wrong_code_counts_attempts_then_blocks(client, app):
    raw_register(client, STUDENT)
    good = last_code(app, STUDENT["email"])
    wrong = "000000" if good != "000000" else "111111"
    for left in (4, 3, 2, 1):
        resp = verify(client, STUDENT["email"], wrong)
        assert resp.status_code == 400
        assert f"{left} attempt" in resp.get_json()["error"]
    assert verify(client, STUDENT["email"], wrong).status_code == 429
    # after too many attempts even the right code no longer works
    assert verify(client, STUDENT["email"], good).status_code == 429
    assert client.get("/api/me").status_code == 401


def test_us1_expired_code_rejected(client, app):
    raw_register(client, STUDENT)
    code = last_code(app, STUDENT["email"])
    age_code(app, STUDENT["email"], minutes=16)
    resp = verify(client, STUDENT["email"], code)
    assert resp.status_code == 400 and "expired" in resp.get_json()["error"]


def test_us1_resend_has_cooldown_and_replaces_old_code(client, app):
    raw_register(client, STUDENT)
    old = last_code(app, STUDENT["email"])
    too_soon = client.post("/api/resend-code", json={"email": STUDENT["email"]})
    assert too_soon.status_code == 429 and too_soon.get_json()["retry_after"] > 0

    age_code(app, STUDENT["email"], seconds=61)
    assert client.post("/api/resend-code", json={"email": STUDENT["email"]}).status_code == 200
    new = last_code(app, STUDENT["email"])
    assert len(app.extensions["mail_outbox"]) == 2
    if new != old:
        assert verify(client, STUDENT["email"], old).status_code == 400
    assert verify(client, STUDENT["email"], new).status_code == 200


def test_us1_resend_for_unknown_email_gives_generic_answer(client, app):
    resp = client.post("/api/resend-code", json={"email": "nobody@stu.sdu.edu.kz"})
    assert resp.status_code == 200
    assert app.extensions["mail_outbox"] == []


def test_us1_verified_email_cannot_be_verified_again(client, app):
    register(client, email=STUDENT["email"])
    resp = verify(client, STUDENT["email"], "123456")
    assert resp.status_code == 409


def test_us1_pending_email_cannot_be_taken_while_code_is_valid(client, app):
    raw_register(client, STUDENT)
    resp = raw_register(client, {**STUDENT, "full_name": "Someone Else", "password": "otherpass12"})
    assert resp.status_code == 409
    assert "not confirmed" in resp.get_json()["error"]
    assert count(app, User) == 1


def test_us1_abandoned_unverified_account_can_register_again(client, app):
    raw_register(client, STUDENT)
    age_code(app, STUDENT["email"], minutes=16)  # first code expired unused
    resp = raw_register(client, {**STUDENT, "full_name": "Aigerim S.", "password": PASSWORD})
    assert resp.status_code == 201
    assert count(app, User) == 1
    assert verify(client, STUDENT["email"], last_code(app, STUDENT["email"])).status_code == 200
    client.post("/api/logout")
    assert client.post("/api/login", json={"email": STUDENT["email"], "password": PASSWORD}).status_code == 200


def test_us1_mail_failure_returns_503(client, app, monkeypatch):
    from uniflow import auth
    from uniflow.mailer import MailError

    def broken(user):
        raise MailError("smtp down")
    monkeypatch.setattr(auth, "issue_code", broken)
    resp = raw_register(client, STUDENT)
    assert resp.status_code == 503
    assert set(resp.get_json()) == {"error"}


def test_us1_verify_page_loads(client):
    page = client.get("/verify?email=220103001@stu.sdu.edu.kz")
    assert page.status_code == 200
    assert 'id="code"' in page.get_data(as_text=True)
