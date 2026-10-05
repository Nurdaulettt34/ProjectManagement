"""Database schema (PostgreSQL). Keep in sync with migrations/versions/."""
import enum
import uuid

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import deferred

from ai.schema import DOC_TYPES
from .extensions import db


class UserRole(str, enum.Enum):
    student = "student"
    applicant = "applicant"
    staff = "staff"
    admin = "admin"


SELF_REGISTER_ROLES = (UserRole.student.value, UserRole.applicant.value)


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processed = "processed"
    failed = "failed"


class FieldState(str, enum.Enum):
    ok = "ok"
    missing = "missing"
    unclear = "unclear"
    corrected = "corrected"


class AIMethod(str, enum.Enum):
    rules = "rules"
    llm = "llm"


# Enum types are bound to the metadata, so a type shared by several tables
# (ai_method) is created once by create_all() / dropped once by drop_all().
user_role_enum = db.Enum(UserRole, name="user_role", metadata=db.metadata)
document_status_enum = db.Enum(DocumentStatus, name="document_status", metadata=db.metadata)
field_state_enum = db.Enum(FieldState, name="field_state", metadata=db.metadata)
ai_method_enum = db.Enum(AIMethod, name="ai_method", metadata=db.metadata)

DOC_TYPES_SQL = ", ".join(f"'{t}'" for t in DOC_TYPES)


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
        db.Index("ix_users_email", "email", unique=True),
    )

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                   server_default=text("gen_random_uuid()"))
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(user_role_enum, nullable=False, default=UserRole.student)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    # NULL until the user enters the code sent to the mailbox; such accounts cannot log in.
    email_verified_at = db.Column(db.DateTime(timezone=True))
    # NULL until the user finishes (or skips) the welcome tour.
    onboarded_at = db.Column(db.DateTime(timezone=True))

    documents = db.relationship("Document", back_populates="user",
                                cascade="all, delete-orphan", passive_deletes=True)
    verification = db.relationship("EmailVerification", back_populates="user", uselist=False,
                                   cascade="all, delete-orphan", passive_deletes=True)

    @property
    def is_verified(self):
        return self.email_verified_at is not None

    def to_dict(self):
        return {
            "id": str(self.id),
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role.value,
            "email_verified": self.is_verified,
            "onboarded": self.onboarded_at is not None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmailVerification(db.Model):
    """One active 6-digit code per user. Only an HMAC of the code is stored."""
    __tablename__ = "email_verifications"
    __table_args__ = (
        db.UniqueConstraint("user_id", name="uq_email_verifications_user_id"),
        db.CheckConstraint("attempts >= 0", name="ck_email_verifications_attempts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=False)

    user = db.relationship("User", back_populates="verification")


class Department(db.Model):
    """Prepared for US11 (routing) and US14 (workflow rules); seeded only."""
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    code = db.Column(db.String(20), nullable=False, unique=True)


class Document(db.Model):
    __tablename__ = "documents"
    __table_args__ = (
        db.CheckConstraint("size_bytes > 0", name="ck_documents_size_positive"),
        db.CheckConstraint("file_ext IN ('pdf', 'docx')", name="ck_documents_file_ext"),
        db.Index("ix_documents_user_id", "user_id"),
    )

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
                   server_default=text("gen_random_uuid()"))
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    file_ext = db.Column(db.String(10), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    # The original file lives in the database (BYTEA). Deferred: lists never load it.
    file_data = deferred(db.Column(db.LargeBinary, nullable=False))
    status = db.Column(document_status_enum, nullable=False, default=DocumentStatus.uploaded)
    error_message = db.Column(db.Text)
    extracted_text = deferred(db.Column(db.Text))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

    user = db.relationship("User", back_populates="documents")
    classification = db.relationship("DocumentClassification", back_populates="document", uselist=False,
                                     cascade="all, delete-orphan", passive_deletes=True)
    fields = db.relationship("ExtractedField", back_populates="document", order_by="ExtractedField.id",
                             cascade="all, delete-orphan", passive_deletes=True)
    summary = db.relationship("DocumentSummary", back_populates="document", uselist=False,
                              cascade="all, delete-orphan", passive_deletes=True)


class DocumentClassification(db.Model):
    __tablename__ = "document_classifications"
    __table_args__ = (
        db.UniqueConstraint("document_id", name="uq_document_classifications_document_id"),
        db.CheckConstraint(f"doc_type IN ({DOC_TYPES_SQL})", name="ck_document_classifications_doc_type"),
        db.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_document_classifications_confidence"),
    )

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(UUID(as_uuid=True), db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    doc_type = db.Column(db.String(32), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    method = db.Column(ai_method_enum, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

    document = db.relationship("Document", back_populates="classification")


class ExtractedField(db.Model):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        db.UniqueConstraint("document_id", "field_name", name="uq_extracted_fields_document_field"),
        # US4: a missing field can never carry a value -> nothing can be invented
        db.CheckConstraint("state <> 'missing' OR value IS NULL", name="ck_extracted_fields_missing_is_null"),
    )

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(UUID(as_uuid=True), db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    field_name = db.Column(db.String(64), nullable=False)
    value = db.Column(db.Text)
    state = db.Column(field_state_enum, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now(),
                           onupdate=func.now())

    document = db.relationship("Document", back_populates="fields")

    def to_dict(self):
        return {"name": self.field_name, "value": self.value, "state": self.state.value}


class DocumentSummary(db.Model):
    __tablename__ = "document_summaries"
    __table_args__ = (
        db.UniqueConstraint("document_id", name="uq_document_summaries_document_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(UUID(as_uuid=True), db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    bullets = db.Column(JSONB, nullable=False)
    method = db.Column(ai_method_enum, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

    document = db.relationship("Document", back_populates="summary")

    def to_dict(self):
        return {
            "bullets": self.bullets,
            "method": self.method.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
