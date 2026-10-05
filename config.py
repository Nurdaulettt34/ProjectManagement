"""Application configuration.

All secrets and connection strings come from environment variables
(locally: from a `.env` file, see `.env.example`). Nothing is generated at
start-up and nothing is stored on the local disk.

Config is read from the environment at *create_app() time* (not at import
time), so tests can change environment variables safely.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # does not override variables that are already set

INSECURE_SECRET_PREFIXES = ("dev-", "change-me", "changeme")


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def normalize_db_url(url):
    """Accept the URL formats Render/Neon/Heroku hand out and force the
    psycopg (v3) driver that we install."""
    if not url:
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class BaseConfig:
    NAME = "base"
    DEBUG = False
    TESTING = False
    DB_ENV_VAR = "DATABASE_URL"
    DEFAULT_DB_URL = None

    @classmethod
    def load(cls):
        return {
            "ENV_NAME": cls.NAME,
            "DEBUG": cls.DEBUG,
            "TESTING": cls.TESTING,
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "SQLALCHEMY_DATABASE_URI": normalize_db_url(
                os.environ.get(cls.DB_ENV_VAR) or cls.DEFAULT_DB_URL
            ),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
            # 20 MB file + a little room for the multipart envelope
            "MAX_FILE_SIZE": 20 * 1024 * 1024,
            "MAX_CONTENT_LENGTH": 20 * 1024 * 1024 + 64 * 1024,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": False,
            # --- AI ---
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY") or None,
            "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            "AI_CONFIDENCE_THRESHOLD": float(os.environ.get("AI_CONFIDENCE_THRESHOLD", "0.5")),
            # --- Registration rules ---
            # Students must use a university mailbox: name@sdu.edu.kz or name@<sub>.sdu.edu.kz.
            # Applicants (future students) may use any email.
            "STUDENT_EMAIL_DOMAIN": os.environ.get("STUDENT_EMAIL_DOMAIN", "sdu.edu.kz").strip().lower().lstrip("@"),
            # --- Email verification (6-digit code) ---
            "VERIFICATION_CODE_TTL_MINUTES": int(os.environ.get("VERIFICATION_CODE_TTL_MINUTES", "15")),
            "VERIFICATION_MAX_ATTEMPTS": int(os.environ.get("VERIFICATION_MAX_ATTEMPTS", "5")),
            "VERIFICATION_RESEND_SECONDS": int(os.environ.get("VERIFICATION_RESEND_SECONDS", "60")),
            # --- Outgoing mail ---
            # MAIL_BACKEND: smtp (real email) | console (print the email to the server log).
            # Default: smtp when MAIL_SERVER is set, otherwise console.
            "MAIL_BACKEND": (os.environ.get("MAIL_BACKEND") or
                             ("smtp" if os.environ.get("MAIL_SERVER") else "console")).strip().lower(),
            "MAIL_SERVER": os.environ.get("MAIL_SERVER") or None,
            "MAIL_PORT": int(os.environ.get("MAIL_PORT", "587")),
            "MAIL_USERNAME": os.environ.get("MAIL_USERNAME") or None,
            "MAIL_PASSWORD": os.environ.get("MAIL_PASSWORD") or None,
            "MAIL_USE_TLS": env_bool("MAIL_USE_TLS", True),
            "MAIL_USE_SSL": env_bool("MAIL_USE_SSL", False),
            "MAIL_FROM": (os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME")
                          or "UniFlow <no-reply@uniflow.local>"),
        }

    @classmethod
    def validate(cls, cfg):
        if not cfg["SQLALCHEMY_DATABASE_URI"]:
            raise RuntimeError(
                f"{cls.DB_ENV_VAR} is not set. Copy .env.example to .env "
                "or run the project with `docker compose up`."
            )
        if not cfg["SECRET_KEY"]:
            raise RuntimeError(
                "SECRET_KEY is not set. Put it in .env (see .env.example). "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )


class DevelopmentConfig(BaseConfig):
    NAME = "development"
    DEBUG = True


class TestingConfig(BaseConfig):
    NAME = "testing"
    TESTING = True
    DB_ENV_VAR = "TEST_DATABASE_URL"
    DEFAULT_DB_URL = "postgresql+psycopg://uniflow:uniflow@localhost:5432/uniflow_test"

    @classmethod
    def load(cls):
        cfg = super().load()
        cfg["SECRET_KEY"] = "testing-only-secret-key"
        cfg["ANTHROPIC_API_KEY"] = None  # tests are always offline and deterministic
        cfg["MAIL_BACKEND"] = "memory"   # emails are collected in app.extensions["mail_outbox"]
        cfg["STUDENT_EMAIL_DOMAIN"] = "sdu.edu.kz"
        cfg["VERIFICATION_CODE_TTL_MINUTES"] = 15
        cfg["VERIFICATION_MAX_ATTEMPTS"] = 5
        cfg["VERIFICATION_RESEND_SECONDS"] = 60
        return cfg


class ProductionConfig(BaseConfig):
    NAME = "production"

    @classmethod
    def load(cls):
        cfg = super().load()
        cfg["SESSION_COOKIE_SECURE"] = True
        # In production codes are emailed for real unless MAIL_BACKEND=console is set explicitly.
        if not os.environ.get("MAIL_BACKEND"):
            cfg["MAIL_BACKEND"] = "smtp"
        return cfg

    @classmethod
    def validate(cls, cfg):
        super().validate(cfg)
        key = cfg["SECRET_KEY"]
        if key.lower().startswith(INSECURE_SECRET_PREFIXES) or len(key) < 32:
            raise RuntimeError("SECRET_KEY looks like a development value. Use a random key of 32+ characters.")


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
