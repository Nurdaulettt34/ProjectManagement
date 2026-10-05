"""Fixtures. Tests run against a separate PostgreSQL database
(TEST_DATABASE_URL). Tables are created once per test session and
emptied (TRUNCATE) before every test."""
import os

import pytest
from sqlalchemy import text

from config import normalize_db_url
from uniflow import create_app
from uniflow.extensions import db

from .helpers import register


@pytest.fixture(scope="session")
def app():
    test_url = normalize_db_url(os.environ.get("TEST_DATABASE_URL"))
    main_url = normalize_db_url(os.environ.get("DATABASE_URL"))
    if test_url and main_url and test_url == main_url:
        pytest.exit("TEST_DATABASE_URL must point to a separate database (tests delete all data).", returncode=2)

    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def clean_db(app):
    with app.app_context():
        tables = ", ".join(t.name for t in db.metadata.sorted_tables)
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        db.session.commit()
        db.session.remove()
    app.extensions["mail_outbox"] = []
    yield


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """Registered, email confirmed, logged in as a student."""
    assert register(client).status_code == 201
    return client


