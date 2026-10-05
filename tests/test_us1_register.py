"""US1 Register an Account — test scripts, G/W/T scenarios, rules."""
import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from uniflow.extensions import db
from uniflow.models import User, UserRole

from .helpers import count, last_code, register

VALID = {"full_name": "Aigerim Sadykova", "email": "aigerim@stu.sdu.edu.kz",
         "password": "supersecret1", "role": "student"}


# --- Test scripts -----------------------------------------------------------

def test_us1_valid_registration_data_creates_account(client, app):
    resp = client.post("/api/register", json=VALID)
    assert resp.status_code == 201
    assert count(app, User) == 1
    with app.app_context():
        user = User.query.one()
        assert user.full_name == "Aigerim Sadykova"
        assert user.role == UserRole.student
        assert user.password_hash != VALID["password"]
        assert check_password_hash(user.password_hash, VALID["password"])


def test_us1_valid_email_and_password_registration_succeeds(client):
    resp = register(client, email=VALID["email"], password=VALID["password"],
                    full_name=VALID["full_name"], role="applicant")
    assert resp.status_code == 201
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["email"] == VALID["email"]
    assert me.get_json()["user"]["role"] == "applicant"


def test_us1_existing_email_registration_rejected(client, app):
    register(client, email=VALID["email"], password=VALID["password"], full_name=VALID["full_name"])
    client.post("/api/logout")
    resp = client.post("/api/register", json={**VALID, "email": "AIGERIM@Stu.SDU.edu.kz", "full_name": "Other"})
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "This email is already registered"}
    assert count(app, User) == 1


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "user@@stu.sdu.edu.kz", "user@uni..edu", "user name@stu.sdu.edu.kz"])
def test_us1_invalid_email_validation_message_displayed(client, app, email):
    resp = client.post("/api/register", json={**VALID, "email": email})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Please enter a valid email address."
    assert count(app, User) == 0


def test_us1_password_shorter_than_8_rejected(client, app):
    resp = client.post("/api/register", json={**VALID, "password": "1234567"})
    assert resp.status_code == 400
    assert "at least 8 characters" in resp.get_json()["error"]
    assert count(app, User) == 0


# --- Given/When/Then --------------------------------------------------------

def test_us1_gwt_successful_registration(client, app):
    # Given the user is on the registration page
    page = client.get("/register")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for field_id in ('id="full_name"', 'id="email"', 'name="role"', 'id="password"'):
        assert field_id in html
    # When they enter valid data and click Register
    resp = client.post("/api/register", json=VALID)
    # Then a new account is created ...
    assert resp.status_code == 201
    assert count(app, User) == 1
    # ... and after confirming the emailed code the user can access the system
    code = last_code(app, VALID["email"])
    assert client.post("/api/verify-email", json={"email": VALID["email"], "code": code}).status_code == 200
    assert client.get("/api/me").status_code == 200
    assert client.get("/app", follow_redirects=True).status_code == 200


def test_us1_gwt_email_already_exists(client):
    # Given an account with the entered email already exists
    register(client, email=VALID["email"], password=VALID["password"], full_name=VALID["full_name"])
    client.post("/api/logout")
    # When the user tries to register
    resp = client.post("/api/register", json={**VALID, "password": "anotherpass1"})
    # Then the system displays a message that the email is already registered
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "This email is already registered"


# --- Rule-oriented ----------------------------------------------------------

def test_us1_rule_email_must_be_valid_format(client):
    assert client.post("/api/register", json={**VALID, "email": "student.university.edu"}).status_code == 400


def test_us1_rule_email_must_be_unique_in_code(client):
    assert register(client, email="x@stu.sdu.edu.kz").status_code == 201
    assert register(client, email="x@stu.sdu.edu.kz").status_code == 409


def test_us1_rule_email_unique_enforced_by_database(app):
    with app.app_context():
        db.session.add(User(full_name="A", email="same@stu.sdu.edu.kz", password_hash="h", role=UserRole.student))
        db.session.commit()
        db.session.add(User(full_name="B", email="same@stu.sdu.edu.kz", password_hash="h", role=UserRole.student))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_us1_rule_email_stored_in_lower_case(client, app):
    client.post("/api/register", json={**VALID, "email": "  Mixed.Case@Stu.SDU.EDU.KZ "})
    with app.app_context():
        assert User.query.one().email == "mixed.case@stu.sdu.edu.kz"


def test_us1_rule_password_at_least_8_characters_boundary(client, app):
    assert client.post("/api/register", json={**VALID, "password": "12345678"}).status_code == 201
    assert count(app, User) == 1


@pytest.mark.parametrize("field", ["full_name", "email", "password", "role"])
@pytest.mark.parametrize("empty", ["", "   ", None])
def test_us1_rule_required_fields_cannot_be_empty(client, app, field, empty):
    resp = client.post("/api/register", json={**VALID, field: empty})
    assert resp.status_code == 400
    assert "Required fields cannot be empty" in resp.get_json()["error"]
    assert count(app, User) == 0


def test_us1_rule_missing_json_body_rejected(client, app):
    resp = client.post("/api/register", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    assert count(app, User) == 0


@pytest.mark.parametrize("role", ["staff", "admin", "superuser"])
def test_us1_rule_only_student_or_applicant_can_self_register(client, app, role):
    resp = client.post("/api/register", json={**VALID, "role": role})
    assert resp.status_code == 400
    assert count(app, User) == 0
