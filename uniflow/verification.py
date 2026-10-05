"""Email verification with a 6-digit code.

- A code lives VERIFICATION_CODE_TTL_MINUTES and allows VERIFICATION_MAX_ATTEMPTS tries.
- A new code can be requested every VERIFICATION_RESEND_SECONDS; it replaces the old one.
- Only an HMAC-SHA256 of the code (keyed with SECRET_KEY) is stored in the database.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from .extensions import db
from .mailer import send_mail
from .models import EmailVerification

CODE_RE = re.compile(r"^\d{6}$")


def now_utc():
    return datetime.now(timezone.utc)


def _hash(code, user_id):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def normalize_code(raw):
    """'123 456' / ' 123456 ' -> '123456'; anything else -> None."""
    if not isinstance(raw, str):
        return None
    code = re.sub(r"[\s-]", "", raw)
    return code if CODE_RE.match(code) else None


def code_is_active(user):
    v = user.verification
    return v is not None and now_utc() <= v.expires_at


def resend_wait_seconds(user):
    """Seconds left before another code may be sent (0 = may send now)."""
    v = user.verification
    if v is None:
        return 0
    elapsed = (now_utc() - v.sent_at).total_seconds()
    left = current_app.config["VERIFICATION_RESEND_SECONDS"] - elapsed
    return max(0, int(left + 0.999))


def issue_code(user):
    """Create or replace the user's code, store its hash and email it.
    The user must already be flushed (has an id). Raises MailError."""
    cfg = current_app.config
    code = f"{secrets.randbelow(10 ** 6):06d}"
    now = now_utc()
    v = user.verification
    if v is None:
        v = EmailVerification(user=user)
        db.session.add(v)
    v.code_hash = _hash(code, user.id)
    v.expires_at = now + timedelta(minutes=cfg["VERIFICATION_CODE_TTL_MINUTES"])
    v.attempts = 0
    v.sent_at = now
    db.session.commit()

    ttl = cfg["VERIFICATION_CODE_TTL_MINUTES"]
    body = (
        f"Hello, {user.full_name}!\n\n"
        f"Your UniFlow verification code is: {code}\n\n"
        f"Enter it on the confirmation page to activate your account. "
        f"The code is valid for {ttl} minutes.\n\n"
        "If you did not create a UniFlow account, just ignore this email - "
        "the account will not be activated without the code.\n\n"
        "- UniFlow, SDU document assistant"
    )
    send_mail(user.email, f"UniFlow verification code: {code}", body, meta={"code": code})
    return code


def check_code(user, code):
    """Return (ok, error_message, http_status). On success the email is marked
    verified and the code is deleted."""
    cfg = current_app.config
    max_attempts = cfg["VERIFICATION_MAX_ATTEMPTS"]
    v = user.verification
    if v is None:
        return False, "There is no active code. Request a new one.", 400
    if v.attempts >= max_attempts:
        return False, "Too many incorrect attempts. Request a new code.", 429
    if now_utc() > v.expires_at:
        return False, "This code has expired. Request a new one.", 400

    if not hmac.compare_digest(v.code_hash, _hash(code, user.id)):
        v.attempts += 1
        db.session.commit()
        left = max_attempts - v.attempts
        if left <= 0:
            return False, "Too many incorrect attempts. Request a new code.", 429
        return False, f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left.", 400

    user.email_verified_at = now_utc()
    db.session.delete(v)
    db.session.commit()
    return True, None, 200
