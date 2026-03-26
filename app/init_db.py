"""Database initialization, auto-migration, and seed data."""

import json
import os
import secrets
from decimal import Decimal
from pathlib import Path

from app import db
from app.models import User, Customer


def _seed_customers():
    """Load seed data from seed_data.json if customers table is empty."""
    if Customer.query.count() > 0:
        return

    seed_file = Path(__file__).parent.parent / "seed_data.json"
    if not seed_file.exists():
        return

    try:
        data = json.loads(seed_file.read_text())
        customers = data.get("customers", [])
        for c in customers:
            db.session.add(Customer(
                name=c["name"],
                address=c.get("address") or None,
                city=c.get("city") or None,
                phone=c.get("phone") or None,
                notes=c.get("notes") or None,
                balance=Decimal(str(c.get("balance", "0"))),
                status=c.get("status", "active"),
                tax_exempt=c.get("tax_exempt", False),
                lead_source=c.get("lead_source") or None,
            ))
        db.session.commit()
        print(f"  Seeded {len(customers)} customers/leads from seed_data.json")
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"  Warning: failed to seed customers: {e}")
        traceback.print_exc()


def init_database():
    """Initialize database tables and create default admin user."""
    # Widen phone column if Postgres has old 20-char limit
    try:
        db.session.execute(db.text(
            "ALTER TABLE customers ALTER COLUMN phone TYPE VARCHAR(30)"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

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

    # Seed customers/leads from seed_data.json if table is empty
    _seed_customers()
