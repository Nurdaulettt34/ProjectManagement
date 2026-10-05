"""initial schema: users, departments, documents, AI results

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DOC_TYPES = ("certificate", "application_form", "request", "transcript",
             "id_document", "internal_form", "other")

user_role = postgresql.ENUM("student", "applicant", "staff", "admin", name="user_role", create_type=False)
document_status = postgresql.ENUM("uploaded", "processed", "failed", name="document_status", create_type=False)
field_state = postgresql.ENUM("ok", "missing", "unclear", "corrected", name="field_state", create_type=False)
ai_method = postgresql.ENUM("rules", "llm", name="ai_method", create_type=False)
ENUMS = (user_role, document_status, field_state, ai_method)


def upgrade():
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_ext", sa.String(10), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file_data", sa.LargeBinary, nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("extracted_text", sa.Text),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("size_bytes > 0", name="ck_documents_size_positive"),
        sa.CheckConstraint("file_ext IN ('pdf', 'docx')", name="ck_documents_file_ext"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])

    doc_types_sql = ", ".join(f"'{t}'" for t in DOC_TYPES)
    op.create_table(
        "document_classifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("method", ai_method, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", name="uq_document_classifications_document_id"),
        sa.CheckConstraint(f"doc_type IN ({doc_types_sql})", name="ck_document_classifications_doc_type"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_document_classifications_confidence"),
    )

    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("value", sa.Text),
        sa.Column("state", field_state, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "field_name", name="uq_extracted_fields_document_field"),
        sa.CheckConstraint("state <> 'missing' OR value IS NULL", name="ck_extracted_fields_missing_is_null"),
    )

    op.create_table(
        "document_summaries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bullets", postgresql.JSONB, nullable=False),
        sa.Column("method", ai_method, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", name="uq_document_summaries_document_id"),
    )


def downgrade():
    op.drop_table("document_summaries")
    op.drop_table("extracted_fields")
    op.drop_table("document_classifications")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("departments")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
