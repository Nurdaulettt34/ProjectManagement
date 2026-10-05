"""US1: registration (with email verification), login, logout, current user.

Rules:
- students register only with a university email (@sdu.edu.kz or @<sub>.sdu.edu.kz);
- applicants (future students) may use any email;
- every new account must confirm its email with a 6-digit code before it can log in.
"""
import re
import uuid
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .errors import error
from .extensions import db
from .mailer import MailError
from .models import SELF_REGISTER_ROLES, User, UserRole
from .verification import check_code, code_is_active, issue_code, normalize_code, resend_wait_seconds

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 256
DUPLICATE_EMAIL_MSG = "This email is already registered"
PENDING_EMAIL_MSG = ("This email is already registered but not confirmed yet. "
                     "Enter the code from your inbox, or log in to get a new one.")
MAIL_FAILED_MSG = "We couldn't send the verification email. Please try again in a few minutes."
REQUIRED_FIELDS = ("full_name", "email", "password", "role")


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def load_current_user():
    """Always re-read the user from the session (never trust a stale g)."""
    g.user = None
    raw = session.get("user_id")
    if not raw:
        return None
    try:
        user = db.session.get(User, uuid.UUID(raw))
    except (ValueError, TypeError):
        user = None
    if user is None or not user.is_verified:
        session.clear()  # account was deleted, never confirmed, or cookie is garbage
        user = None
    g.user = user
    return user


def login_user(user):
    session.clear()  # prevent session fixation
    session["user_id"] = str(user.id)


def login_required_api(view):
    """JSON endpoints: 401 instead of a redirect."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if load_current_user() is None:
            return error("Not authenticated.", 401)
        return view(*args, **kwargs)
    return wrapped


def login_required_page(view):
    """HTML pages: anonymous visitors go to /login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if load_current_user() is None:
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)
    return wrapped


def wants_html():
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "text/html"


def login_required_hybrid(view):
    """For URLs opened both by the browser and by fetch(): a browser
    navigation without a session is redirected to /login, a script gets 401."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if load_current_user() is None:
            if wants_html():
                return redirect(url_for("auth.login_page"))
            return error("Not authenticated.", 401)
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Validation (US1 rules)
# ---------------------------------------------------------------------------
def _as_text(value):
    return value.strip() if isinstance(value, str) else ""


def student_domain():
    return current_app.config.get("STUDENT_EMAIL_DOMAIN", "sdu.edu.kz")


def is_university_email(email, domain=None):
    """name@sdu.edu.kz or name@stu.sdu.edu.kz -> True; name@notsdu.edu.kz -> False."""
    domain = domain or student_domain()
    host = email.rsplit("@", 1)[-1].lower()
    return host == domain or host.endswith("." + domain)


def student_email_message():
    d = student_domain()
    return (f"Students must register with their SDU university email "
            f"(ending in @{d}, for example name@stu.{d}). Applicants can use any email.")


def validate_registration(data):
    """Return (clean_data, None) or (None, error_message)."""
    clean = {
        "full_name": re.sub(r"\s+", " ", _as_text(data.get("full_name"))),
        "email": _as_text(data.get("email")).lower(),
        "password": data.get("password") if isinstance(data.get("password"), str) else "",
        "role": _as_text(data.get("role")).lower(),
    }
    missing = [f for f in REQUIRED_FIELDS if not clean[f].strip()]
    if missing:
        names = ", ".join(f.replace("_", " ") for f in missing)
        return None, f"Required fields cannot be empty: {names}."
    if len(clean["full_name"]) < 2 or len(clean["full_name"]) > 120:
        return None, "Full name must be between 2 and 120 characters."
    if len(clean["email"]) > 254 or not EMAIL_RE.match(clean["email"]) or ".." in clean["email"]:
        return None, "Please enter a valid email address."
    if clean["role"] not in SELF_REGISTER_ROLES:
        return None, "Role must be either student or applicant."
    if clean["role"] == UserRole.student.value and not is_university_email(clean["email"]):
        return None, student_email_message()
    if len(clean["password"]) < MIN_PASSWORD:
        return None, f"Password must be at least {MIN_PASSWORD} characters long."
    if len(clean["password"]) > MAX_PASSWORD:
        return None, f"Password must be at most {MAX_PASSWORD} characters long."
    return clean, None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@bp.get("/register")
def register_page():
    if load_current_user():
        return redirect(url_for("pages.workspace"))
    return render_template("register.html", student_domain=student_domain())


@bp.get("/login")
def login_page():
    if load_current_user():
        return redirect(url_for("pages.workspace"))
    return render_template("login.html")


@bp.get("/verify")
def verify_page():
    if load_current_user():
        return redirect(url_for("pages.workspace"))
    email = _as_text(request.args.get("email")).lower()[:254]
    return render_template("verify.html", email=email,
                           resend_seconds=current_app.config["VERIFICATION_RESEND_SECONDS"])


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@bp.post("/api/register")
def api_register():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    clean, message = validate_registration(data)
    if message:
        return error(message, 400)  # invalid data never reaches the database

    user = User.query.filter_by(email=clean["email"]).first()
    if user is not None:
        if user.is_verified:
            return error(DUPLICATE_EMAIL_MSG, 409)
        if code_is_active(user):
            return error(PENDING_EMAIL_MSG, 409)
        # Unconfirmed account whose code has expired: the mailbox owner may start over.
        user.full_name = clean["full_name"]
        user.password_hash = generate_password_hash(clean["password"])
        user.role = UserRole(clean["role"])
    else:
        user = User(
            full_name=clean["full_name"],
            email=clean["email"],
            password_hash=generate_password_hash(clean["password"]),
            role=UserRole(clean["role"]),
        )
        db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:  # two requests raced past the check above
        db.session.rollback()
        return error(DUPLICATE_EMAIL_MSG, 409)

    session.clear()  # nobody is logged in until the email is confirmed
    try:
        issue_code(user)
    except MailError:
        return error(MAIL_FAILED_MSG, 503)

    return jsonify({
        "message": f"Account created. We sent a 6-digit code to {user.email}.",
        "verification_required": True,
        "email": user.email,
        "user": user.to_dict(),
    }), 201


@bp.post("/api/verify-email")
def api_verify_email():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    email = _as_text(data.get("email")).lower()
    code = normalize_code(data.get("code"))
    if not email:
        return error("Email is required.", 400)
    if code is None:
        return error("Enter the 6-digit code from the email.", 400)

    user = User.query.filter_by(email=email).first()
    if user is None:
        return error("There is no active code. Request a new one.", 400)
    if user.is_verified:
        return error("This email is already confirmed. Please log in.", 409)

    ok, message, status = check_code(user, code)
    if not ok:
        return error(message, status)

    login_user(user)
    return jsonify({"message": "Email confirmed. Welcome to UniFlow!",
                    "user": user.to_dict(), "next": url_for("pages.welcome")}), 200


@bp.post("/api/resend-code")
def api_resend_code():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    email = _as_text(data.get("email")).lower()
    if not email:
        return error("Email is required.", 400)
    generic = {"message": "If this email has an unconfirmed account, a new code has been sent.",
               "retry_after": current_app.config["VERIFICATION_RESEND_SECONDS"]}

    user = User.query.filter_by(email=email).first()
    if user is None or user.is_verified:
        return jsonify(generic), 200
    wait = resend_wait_seconds(user)
    if wait > 0:
        resp = jsonify({"error": f"Please wait {wait} s before requesting a new code.", "retry_after": wait})
        return resp, 429
    try:
        issue_code(user)
    except MailError:
        return error(MAIL_FAILED_MSG, 503)
    return jsonify(generic), 200


@bp.post("/api/login")
def api_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    email = _as_text(data.get("email")).lower()
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    if not email or not password:
        return error("Please enter your email and password.", 400)

    user = User.query.filter_by(email=email).first()
    if user is None or not check_password_hash(user.password_hash, password):
        return error("Incorrect email or password.", 401)
    if not user.is_verified:
        return jsonify({
            "error": "Please confirm your email first. Enter the code we sent you or request a new one.",
            "verification_required": True,
            "email": user.email,
        }), 403

    login_user(user)
    return jsonify({"user": user.to_dict()}), 200


@bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"logged_out": True}), 200


@bp.get("/api/me")
@login_required_api
def api_me():
    return jsonify({"user": g.user.to_dict()}), 200
