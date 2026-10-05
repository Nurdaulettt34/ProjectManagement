"""Main page, welcome tour (onboarding) and user profile."""
from uniflow.models import User

from .helpers import PASSWORD, STUDENT_EMAIL, register, upload_pdf


# --- Main (landing) page -------------------------------------------------------

def test_landing_page_is_public(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "/register" in html and "/login" in html


def test_landing_page_shows_workspace_link_when_logged_in(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert "/app" in html


# --- Welcome tour ------------------------------------------------------------

def test_new_user_is_sent_to_welcome_tour_first(client):
    register(client, onboard=False)
    resp = client.get("/app", follow_redirects=False)
    assert resp.status_code == 302 and "/welcome" in resp.headers["Location"]
    assert client.get("/welcome").status_code == 200


def test_completing_tour_opens_workspace(client, app):
    register(client, onboard=False)
    resp = client.post("/api/onboarding/complete")
    assert resp.status_code == 200 and resp.get_json()["next"] == "/app"
    assert client.get("/app").status_code == 200
    with app.app_context():
        assert User.query.one().onboarded_at is not None


def test_tour_stays_available_after_onboarding(auth_client):
    assert auth_client.get("/welcome").status_code == 200
    assert auth_client.get("/app").status_code == 200


def test_onboarding_requires_login(client):
    assert client.post("/api/onboarding/complete").status_code == 401
    assert client.get("/welcome", follow_redirects=False).status_code == 302


# --- Profile -----------------------------------------------------------------

def test_profile_page_and_api_require_login(client):
    assert client.get("/profile", follow_redirects=False).status_code == 302
    assert client.get("/api/profile").status_code == 401


def test_profile_returns_user_and_document_stats(auth_client):
    upload_pdf(auth_client, filename="a.pdf")
    upload_pdf(auth_client, filename="b.pdf")
    doc_id = auth_client.get("/api/documents").get_json()[0]["id"]
    auth_client.post(f"/api/documents/{doc_id}/review")

    data = auth_client.get("/api/profile").get_json()
    assert data["user"]["email"] == STUDENT_EMAIL
    assert data["user"]["email_verified"] is True
    assert data["stats"]["total"] == 2
    assert data["stats"]["reviewed"] == 1
    assert data["stats"]["total"] == data["stats"]["processed"] + data["stats"]["failed"]
    assert len(data["recent_documents"]) == 2
    assert "text" not in data["recent_documents"][0]
    assert data["requests"] is None  # Requests user story not implemented yet
    assert auth_client.get("/profile").status_code == 200


def test_profile_stats_are_per_user(client):
    register(client, email="owner@stu.sdu.edu.kz")
    upload_pdf(client)
    client.post("/api/logout")
    register(client, email="other@stu.sdu.edu.kz")
    assert client.get("/api/profile").get_json()["stats"]["total"] == 0


def test_profile_update_full_name(auth_client):
    resp = auth_client.patch("/api/profile", json={"full_name": "  Aigerim   Sadykova "})
    assert resp.status_code == 200
    assert auth_client.get("/api/me").get_json()["user"]["full_name"] == "Aigerim Sadykova"
    assert auth_client.patch("/api/profile", json={"full_name": "A"}).status_code == 400
    assert auth_client.patch("/api/profile", json={}).status_code == 400


def test_profile_email_and_role_cannot_be_changed(auth_client):
    auth_client.patch("/api/profile", json={"full_name": "New Name", "email": "x@gmail.com", "role": "admin"})
    user = auth_client.get("/api/me").get_json()["user"]
    assert user["email"] == STUDENT_EMAIL and user["role"] == "student"


def test_change_password(auth_client):
    wrong = auth_client.post("/api/profile/password",
                             json={"current_password": "nope-nope", "new_password": "brand-new-pass"})
    assert wrong.status_code == 400
    short = auth_client.post("/api/profile/password",
                             json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 400
    ok = auth_client.post("/api/profile/password",
                          json={"current_password": PASSWORD, "new_password": "brand-new-pass"})
    assert ok.status_code == 200

    auth_client.post("/api/logout")
    assert auth_client.post("/api/login", json={"email": STUDENT_EMAIL, "password": PASSWORD}).status_code == 401
    assert auth_client.post("/api/login",
                            json={"email": STUDENT_EMAIL, "password": "brand-new-pass"}).status_code == 200
