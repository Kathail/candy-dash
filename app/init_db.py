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

    # Add amount_sold column to payments if missing
    try:
        db.session.execute(db.text(
            "ALTER TABLE payments ADD COLUMN amount_sold NUMERIC(10,2) DEFAULT 0"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Migrate old roles (sales, manager) to owner
    try:
        db.session.execute(db.text(
            "UPDATE users SET role = 'owner' WHERE role IN ('sales', 'manager')"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

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
            import logging
            logging.getLogger(__name__).warning(
                "Default admin user created with auto-generated password. "
                "Set ADMIN_PASSWORD env var and restart, or change via /change-password. "
                "Auto-generated password written to: instance/admin_password.txt"
            )
            pw_file = Path(__file__).parent.parent / "instance" / "admin_password.txt"
            pw_file.parent.mkdir(exist_ok=True)
            pw_file.write_text(admin_password)
            pw_file.chmod(0o600)
        else:
            print("  Default admin user created with ADMIN_PASSWORD from environment.")

    # Create demo user if it doesn't exist
    if not User.query.filter_by(username="demo").first():
        demo = User(
            username="demo",
            email="demo@candyroute.local",
            role="demo",
            is_active=True,
        )
        demo.set_password("demo")
        db.session.add(demo)
        db.session.commit()
        print("  Demo user created (username: demo, password: demo)")

    # Create bookkeeper user if it doesn't exist
    if not User.query.filter_by(username="miranda").first():
        bk = User(
            username="miranda",
            email="miranda@candyroute.local",
            role="bookkeeper",
            is_active=True,
        )
        bk_password = os.environ.get("BOOKKEEPER_PASSWORD", "miranda123")
        bk.set_password(bk_password)
        db.session.add(bk)
        db.session.commit()
        print(f"  Bookkeeper user created (username: miranda)")

    # Seed customers/leads from seed_data.json if table is empty
    _seed_customers()
