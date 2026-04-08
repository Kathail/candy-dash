"""App factory for Candy Route Planner."""

import os
from datetime import timedelta
from flask import Flask, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    )

    # Configuration
    flask_env = os.environ.get("FLASK_ENV", "production")
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key and flask_env != "development":
        raise RuntimeError(
            "SECRET_KEY environment variable is required in production. "
            "Set FLASK_ENV=development to use the dev fallback."
        )
    app.config["SECRET_KEY"] = secret_key or "dev-secret-key-change-in-production"

    database_url = os.environ.get("DATABASE_URL", "sqlite:///candy_route.db")
    # Render provides postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Recycle stale Postgres connections before the server drops them
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 5,
        "max_overflow": 10,
    }
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 30 days
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB upload limit

    # Secure cookie settings
    app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if flask_env != "development":
        app.config["SESSION_COOKIE_SECURE"] = True

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)

    # Sentry error monitoring (set SENTRY_DSN env var to enable)
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)
        except ImportError:
            app.logger.warning("SENTRY_DSN set but sentry-sdk not installed")

    # User loader
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        if user and not user.is_active:
            return None
        return user

    # Register blueprints
    from app.routes import register_blueprints
    register_blueprints(app)

    # Read-only guard: block writes for demo users
    @app.before_request
    def readonly_guard():
        from flask_login import current_user as cu
        from flask import request as req, flash, redirect, jsonify, url_for as _url_for
        from app.helpers import safe_redirect
        if not cu.is_authenticated:
            return
        if cu.role not in ("demo",):
            return
        label = "Demo mode"

        # Block all writes except logout
        if req.method in ("POST", "PUT", "DELETE") and req.endpoint not in ("auth.logout", "auth.change_password"):
            if req.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"error": f"{label} — this action is disabled."}), 403
            flash(f"{label} — this action is disabled.", "warning")
            return redirect(safe_redirect(req.referrer))
        # Block report exports and API access
        blocked_prefixes = ("reports.", "api.")
        if req.endpoint and any(req.endpoint.startswith(p) for p in blocked_prefixes):
            if req.args.get("format") in ("csv", "xlsx", "pdf"):
                flash("Demo mode — exports are disabled.", "warning")
                return redirect(safe_redirect(req.referrer))
            if req.endpoint.startswith("api."):
                return jsonify({"error": "Demo mode — API disabled."}), 403

    # Template filters
    from app.helpers import format_currency, format_date
    app.jinja_env.filters["currency"] = format_currency
    app.jinja_env.filters["dateformat"] = format_date

    # Initialize database on first request
    from app.init_db import init_database

    with app.app_context():
        init_database()

    # Global context for mobile bottom nav badges
    @app.context_processor
    def nav_badge_context():
        try:
            from flask import request as _req
            from flask_login import current_user as cu
            if not cu.is_authenticated:
                return {}
            # Skip badge queries on HTMX partial requests (no nav rendered)
            if _req.headers.get("HX-Request"):
                return {}
            from datetime import date as _date
            today = _date.today()
            result = db.session.execute(db.text(
                "SELECT "
                "(SELECT COUNT(*) FROM route_stops WHERE route_date = :today AND completed = false), "
                "(SELECT COUNT(*) FROM customers WHERE balance > 0 AND status = 'active')"
            ), {"today": today}).first()
            return {
                "nav_remaining_stops": result[0] if result else 0,
                "nav_overdue_count": result[1] if result else 0,
            }
        except Exception:
            return {}

    # Health check endpoint
    @app.route("/health")
    def health_check():
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"status": "ok", "db": "connected"}), 200
        except Exception:
            return jsonify({"status": "error", "db": "unavailable"}), 503

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP: allow inline scripts (Alpine.js, Chart.js config), HTMX, and self-hosted assets
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        if flask_env != "development":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app
