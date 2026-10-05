"""User profile and onboarding API.

The profile shows account data and document statistics. Requests and their
statuses will be added here by the Requests user story (the "My requests"
block in the UI is a placeholder until then).
"""
import re

from flask import Blueprint, g, jsonify, request
from sqlalchemy import and_, func
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import MAX_PASSWORD, MIN_PASSWORD, login_required_api
from .documents import brief
from .errors import error
from .extensions import db
from .models import Document, DocumentStatus
from .verification import now_utc

bp = Blueprint("profile", __name__, url_prefix="/api")


def document_stats(user_id):
    total, processed, failed, reviewed, needs_review = db.session.query(
        func.count(Document.id),
        func.count(Document.id).filter(Document.status == DocumentStatus.processed),
        func.count(Document.id).filter(Document.status == DocumentStatus.failed),
        func.count(Document.id).filter(Document.reviewed_at.isnot(None)),
        func.count(Document.id).filter(and_(Document.status == DocumentStatus.processed,
                                            Document.reviewed_at.is_(None))),
    ).filter(Document.user_id == user_id).one()
    return {"total": total, "processed": processed, "failed": failed,
            "reviewed": reviewed, "needs_review": needs_review}


@bp.get("/profile")
@login_required_api
def get_profile():
    recent = (Document.query.filter_by(user_id=g.user.id)
              .order_by(Document.uploaded_at.desc()).limit(5).all())
    return jsonify({
        "user": g.user.to_dict(),
        "stats": document_stats(g.user.id),
        "recent_documents": [brief(d) for d in recent],
        "requests": None,  # filled in by the Requests user story
    }), 200


@bp.patch("/profile")
@login_required_api
def update_profile():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "full_name" not in data:
        return error('Send {"full_name": "..."}.', 400)
    raw = data.get("full_name")
    name = re.sub(r"\s+", " ", raw.strip()) if isinstance(raw, str) else ""
    if len(name) < 2 or len(name) > 120:
        return error("Full name must be between 2 and 120 characters.", 400)
    g.user.full_name = name
    db.session.commit()
    return jsonify({"message": "Profile updated.", "user": g.user.to_dict()}), 200


@bp.post("/profile/password")
@login_required_api
def change_password():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    current = data.get("current_password") if isinstance(data.get("current_password"), str) else ""
    new = data.get("new_password") if isinstance(data.get("new_password"), str) else ""
    if not current or not new:
        return error("Enter your current and new password.", 400)
    if not check_password_hash(g.user.password_hash, current):
        return error("Current password is incorrect.", 400)
    if len(new) < MIN_PASSWORD:
        return error(f"Password must be at least {MIN_PASSWORD} characters long.", 400)
    if len(new) > MAX_PASSWORD:
        return error(f"Password must be at most {MAX_PASSWORD} characters long.", 400)
    if new == current:
        return error("The new password must be different from the current one.", 400)
    g.user.password_hash = generate_password_hash(new)
    db.session.commit()
    return jsonify({"message": "Password changed."}), 200


@bp.post("/onboarding/complete")
@login_required_api
def complete_onboarding():
    if g.user.onboarded_at is None:
        g.user.onboarded_at = now_utc()
        db.session.commit()
    return jsonify({"onboarded": True, "next": "/app"}), 200
