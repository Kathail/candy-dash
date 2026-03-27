"""App factory for Candy Route Planner."""

import os
from flask import Flask, render_template
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
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7  # 7 days

    # Secure cookie settings
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
            from flask_login import current_user as cu
            if not cu.is_authenticated:
                return {}
            from app.models import RouteStop, Customer
            from datetime import date as _date
            today = _date.today()
            remaining_stops = RouteStop.query.filter(
                RouteStop.route_date == today,
                RouteStop.completed.is_(False),
            ).count()
            overdue_count = Customer.query.filter(
                Customer.balance > 0,
                Customer.status == "active",
            ).count()
            return {
                "nav_remaining_stops": remaining_stops,
                "nav_overdue_count": overdue_count,
            }
        except Exception:
            return {}

    # Serve service worker from root so its scope covers the whole app
    @app.route("/sw.js")
    def service_worker():
        from flask import send_from_directory
        return send_from_directory(
            app.static_folder, "sw.js",
            mimetype="application/javascript",
        )

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app
