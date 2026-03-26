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
            # Clean phone: strip "Phone Number" prefix, multiple numbers
            phone = (c.get("phone") or "").strip()
            phone = phone.replace("Phone Number", "").strip()
            if len(phone) > 20:
                # Take first phone number only (split on common separators)
                for sep in [",", "/", "  "]:
                    if sep in phone:
                        phone = phone.split(sep)[0].strip()
                        break
            phone = phone[:50] if phone else None

            # Clean address: strip "Get directions" suffix
            address = (c.get("address") or "").strip()
            address = address.replace("Get directions", "").strip()

            db.session.add(Customer(
                name=c["name"],
                address=address or None,
                city=c.get("city"),
                phone=phone,
                notes=c.get("notes"),
                balance=Decimal(str(c.get("balance", "0"))),
                status=c.get("status", "active"),
                tax_exempt=c.get("tax_exempt", False),
                lead_source=c.get("lead_source"),
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
    db.create_all()

    # Widen phone column if needed (Postgres may have old 20-char limit)
    try:
        db.session.execute(db.text(
            "ALTER TABLE customers ALTER COLUMN phone TYPE VARCHAR(50)"
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
            print(f"\n{'='*50}")
            print(f"  Default admin user created")
            print(f"  Username: admin")
            print(f"  Password: {admin_password}")
            print(f"{'='*50}\n")
        else:
            print("  Default admin user created with ADMIN_PASSWORD from environment.")

    # Seed customers/leads from seed_data.json if table is empty
    _seed_customers()
