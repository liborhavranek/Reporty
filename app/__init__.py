from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFError
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3
import os

csrf = CSRFProtect()
db = SQLAlchemy()
migrate = Migrate(compare_type=True, render_as_batch=True)

def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__)

    # ---- Cesty / limity ----
    BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
    DATA_DIR   = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
    DB_PATH    = os.getenv("SQLITE_PATH", os.path.join(DATA_DIR, "app.db"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "..", "storage", "logos"))
    REPORTS_DIR = os.getenv("REPORTS_DIR", os.path.join(BASE_DIR, "..", "storage", "reports"))  # <—
    MAX_MB     = int(os.getenv("MAX_CONTENT_LENGTH_MB", "5"))

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)  # <— vytvoř adresář pro CSV

    # ---- Konfigurace aplikace ----
    app.config.from_mapping(
        # Bezpečnost
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes"),
        ADMIN_PASS_HASH=os.getenv("ADMIN_PASS_HASH"),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD"),

        # Email
        SMTP_HOST="smtp.gmail.com",
        SMTP_PORT=465,
        SMTP_USER=os.environ.get("SMTP_USER"),
        SMTP_PASS=os.environ.get("SMTP_PASS"),
        CONTACT_TO="liborhavranek91@gmail.com",

        # DB (SQLite)
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.abspath(DB_PATH)}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        # Uploady
        UPLOAD_DIR=UPLOAD_DIR,
        REPORTS_DIR=REPORTS_DIR,               # <— zaregistrované v configu
        MAX_CONTENT_LENGTH=MAX_MB * 1024 * 1024,

        # Dev
        TEMPLATES_AUTO_RELOAD=True,
    )

    if test_config:
        app.config.update(test_config)

    # ---- Init extensions ----
    csrf.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)

    # ---- PRAGMA pro SQLite ----
    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.close()

    # ---- CSRF handler ----
    @app.errorhandler(CSRFError)
    def handle_csrf(e):
        app.logger.error(f"CSRFError: {e.description}")
        return {"ok": False, "error": f"CSRF: {e.description}"}, 400

    @app.context_processor
    def inject_flags():
        from flask import session
        return {"is_admin": bool(session.get("is_admin"))}

    # Načti modely, aby je migrace viděla
    from app import models  # noqa: F401
    from .models.project_model import Project  # noqa
    from .models.suite_model import Suite      # noqa
    from .models.run_model import Run          # noqa

    # Healthcheck
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # Blueprinty
    from app.routes import bp
    from app.admin.routes import admin_bp
    app.register_blueprint(bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app
