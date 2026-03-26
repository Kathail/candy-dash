"""Database initialization, auto-migration, and seed data."""

import os
import secrets
from app import db
from app.models import User


def init_database():
    """Initialize database tables and create default admin user."""
    db.create_all()

    # Create default admin if no users exist
    if User.query.count() == 0:
        admin_password = os.environ.get("ADMIN_PASSWORD")
        generated = False
        if not admin_password:
            admin_password = secrets.token_urlsafe(16)
            generated = True

        admin = User(
            username="admin",
            email="admin@candyroute.local",
            role="admin",
            is_active=True,
        )
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()

        if generated:
            print(f"\n{'='*50}")
            print(f"  Default admin user created")
            print(f"  Username: admin")
            print(f"  Password: {admin_password}")
            print(f"{'='*50}\n")
        else:
            print("  Default admin user created with ADMIN_PASSWORD from environment.")
