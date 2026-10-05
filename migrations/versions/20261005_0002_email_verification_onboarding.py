"""email verification and onboarding

Revision ID: 0002_verification
Revises: 0001_initial
Create Date: 2026-10-05

- users.email_verified_at, users.onboarded_at
- email_verifications (one active code per user, only an HMAC is stored)
Accounts that existed before this revision are treated as verified and onboarded.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_verification"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE users SET email_verified_at = created_at, onboarded_at = created_at")

    op.create_table(
        "email_verifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_email_verifications_user_id"),
        sa.CheckConstraint("attempts >= 0", name="ck_email_verifications_attempts"),
    )


def downgrade():
    op.drop_table("email_verifications")
    op.drop_column("users", "onboarded_at")
    op.drop_column("users", "email_verified_at")
