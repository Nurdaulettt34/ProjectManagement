"""Cross-cutting requirements: configuration, error format, schema."""
import pytest
from sqlalchemy import inspect

from uniflow import create_app
from uniflow.extensions import db

from .helpers import register


def test_secret_key_required_in_production(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


def test_development_secret_rejected_in_production(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "dev-only-insecure-key-change-me")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    with pytest.raises(RuntimeError):
        create_app("production")


def test_database_url_required(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app("development")


def test_secret_key_not_regenerated_on_start(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    assert create_app("production").config["SECRET_KEY"] == create_app("production").config["SECRET_KEY"] == "k" * 64


def test_render_style_database_url_normalized(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    assert create_app("production").config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://")


def test_uses_postgresql(app):
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://")
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"


def test_schema_tables_and_indexes(app):
    with app.app_context():
        insp = inspect(db.engine)
        assert {"users", "departments", "documents", "document_classifications",
                "extracted_fields", "document_summaries", "email_verifications"} <= set(insp.get_table_names())
        user_cols = {c["name"] for c in insp.get_columns("users")}
        assert {"email_verified_at", "onboarded_at"} <= user_cols
        assert "ix_documents_user_id" in {i["name"] for i in insp.get_indexes("documents")}
        assert "ix_users_email" in {i["name"] for i in insp.get_indexes("users")}
        fk = insp.get_foreign_keys("documents")[0]
        assert fk["referred_table"] == "users" and fk["options"].get("ondelete") == "CASCADE"


def test_api_errors_have_uniform_format(auth_client):
    for resp in (
        auth_client.get("/api/documents/not-a-uuid"),
        auth_client.get("/api/documents/00000000-0000-0000-0000-000000000000"),
        auth_client.get("/api/nothing-here"),
        auth_client.put("/api/documents"),
    ):
        assert resp.status_code in (404, 405)
        assert set(resp.get_json()) == {"error"}


def test_me_requires_login(client):
    assert client.get("/api/me").status_code == 401
    register(client)
    assert client.get("/api/me").status_code == 200


def test_seed_creates_departments_staff_and_admin(app):
    from uniflow.models import Department, User, UserRole
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed"])
    assert result.exit_code == 0, result.output
    runner.invoke(args=["seed"])  # idempotent
    with app.app_context():
        assert Department.query.count() >= 5
        assert User.query.filter_by(role=UserRole.staff).count() == 1
        assert User.query.filter_by(role=UserRole.admin).count() == 1
        # seeded accounts can log in right away: no email code, no welcome tour
        assert all(u.email_verified_at and u.onboarded_at for u in User.query.all())


def test_production_sends_real_email_by_default(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    monkeypatch.delenv("MAIL_BACKEND", raising=False)
    monkeypatch.delenv("MAIL_SERVER", raising=False)
    assert create_app("production").config["MAIL_BACKEND"] == "smtp"


def test_development_prints_email_to_console_without_smtp(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 64)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    monkeypatch.delenv("MAIL_BACKEND", raising=False)
    monkeypatch.delenv("MAIL_SERVER", raising=False)
    assert create_app("development").config["MAIL_BACKEND"] == "console"
