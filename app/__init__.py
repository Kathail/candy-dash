"""App factory for Candy Route Planner."""

import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
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
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    turso_url = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
    turso_token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()

    if turso_url and turso_token:
        # Register libsql_client's DBAPI2 driver as a SQLAlchemy dialect
        from sqlalchemy.dialects import registry as dialect_registry
        dialect_registry.register("sqlite.libsql", "app.libsql_dialect", "dialect")

        # Build connection URL for our custom dialect
        # Convert libsql:// to https:// for the HTTP client
        http_url = turso_url.replace("libsql://", "https://")
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            f"sqlite+libsql:///{http_url}?authToken={turso_token}"
        )
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
            "DATABASE_URL", "sqlite:///candy_route.db"
        )

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 31  # 31 days

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    # User loader
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

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

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app
