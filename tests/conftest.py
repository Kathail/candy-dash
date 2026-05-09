"""Shared pytest fixtures."""

import os
import tempfile

import pytest

# Force test config before importing app
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture
def app():
    """Flask app bound to a fresh on-disk SQLite DB per test."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from app import create_app, db as _db

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    with application.app_context():
        # init_db.init_database() already ran in create_app(); start clean.
        _db.session.remove()
        _db.drop_all()
        _db.create_all()
        yield application
        _db.session.remove()

    os.unlink(db_path)


@pytest.fixture
def db(app):
    """SQLAlchemy db bound to the test app."""
    from app import db as _db
    return _db
