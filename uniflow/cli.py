"""`flask seed` — departments and staff/admin accounts (idempotent).
Staff and admin accounts are created only here, never via /api/register."""
import os

import click
from flask import current_app
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Department, User, UserRole
from .verification import now_utc

DEPARTMENTS = [
    ("ADM", "Admissions Office"),
    ("REG", "Registrar's Office"),
    ("DEAN", "Dean's Office"),
    ("ACAD", "Academic Affairs"),
    ("FIN", "Finance and Accounting"),
    ("DORM", "Student Housing"),
    ("MIL", "Military Department"),
    ("IT", "IT Services"),
]

DEV_DEFAULTS = {
    "staff": ("staff@uniflow.edu", "Staff Member", "Staff-Password-2026"),
    "admin": ("admin@uniflow.edu", "System Administrator", "Admin-Password-2026"),
}


def _account(role):
    prefix = f"SEED_{role.upper()}_"
    email_d, name_d, pass_d = DEV_DEFAULTS[role]
    email = os.environ.get(prefix + "EMAIL", email_d).strip().lower()
    password = os.environ.get(prefix + "PASSWORD")
    if not password:
        if current_app.config["ENV_NAME"] == "production":
            raise click.ClickException(f"Set {prefix}PASSWORD before seeding production.")
        password = pass_d
        click.echo(f"  ! {prefix}PASSWORD not set, using the development default for {email}")
    return email, os.environ.get(prefix + "NAME", name_d), password


def register_cli(app):
    @app.cli.command("seed")
    def seed():
        """Create departments and the staff/admin accounts."""
        for code, name in DEPARTMENTS:
            dep = Department.query.filter_by(code=code).first()
            if dep is None:
                db.session.add(Department(code=code, name=name))
            else:
                dep.name = name
        click.echo(f"Departments: {len(DEPARTMENTS)}")

        for role in ("staff", "admin"):
            email, name, password = _account(role)
            if User.query.filter_by(email=email).first():
                click.echo(f"  {role}: {email} already exists")
                continue
            now = now_utc()  # seeded accounts are trusted: no email code, no welcome tour
            db.session.add(User(full_name=name, email=email, role=UserRole(role),
                                password_hash=generate_password_hash(password),
                                email_verified_at=now, onboarded_at=now))
            click.echo(f"  {role}: {email} created")
        db.session.commit()
        click.echo("Seed complete.")
