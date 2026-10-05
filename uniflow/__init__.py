"""UniFlow — Intelligent University Document Management Assistant."""
import os

from flask import Flask

from config import CONFIGS
from .extensions import db, migrate


def create_app(config_name=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    if config_name not in CONFIGS:
        raise RuntimeError(f"Unknown APP_ENV '{config_name}'. Use one of: {', '.join(CONFIGS)}.")
    cfg_class = CONFIGS[config_name]
    cfg = cfg_class.load()
    cfg_class.validate(cfg)  # no SECRET_KEY / DATABASE_URL -> refuse to start

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, template_folder=os.path.join(base, "templates"),
                static_folder=os.path.join(base, "static"))
    app.config.update(cfg)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(base, "migrations"))

    from . import models  # noqa: F401  (register tables for Alembic)
    from .auth import bp as auth_bp
    from .cli import register_cli
    from .documents import bp as documents_bp
    from .errors import register_error_handlers
    from .pages import bp as pages_bp
    from .profile import bp as profile_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(profile_bp)
    register_error_handlers(app)
    register_cli(app)
    return app
