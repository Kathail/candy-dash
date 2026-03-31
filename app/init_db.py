"""Database initialization, auto-migration, and seed data."""

import json
import logging
import os
import secrets
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from app import db
from app.models import User, Customer

log = logging.getLogger(__name__)


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
        log.info("Seeded %d customers/leads from seed_data.json", len(customers))
    except Exception as e:
        db.session.rollback()
        log.warning("Failed to seed customers: %s", e, exc_info=True)


def init_database():
    """Initialize database tables and create default admin user."""
    db.create_all()

    # Widen phone column if Postgres has old 20-char limit
    try:
        db.session.execute(db.text(
            "ALTER TABLE customers ALTER COLUMN phone TYPE VARCHAR(30)"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.debug("phone column migration skipped: %s", e)

    # Add payment_type column to invoices if missing
    try:
        db.session.execute(db.text(
            "ALTER TABLE invoices ADD COLUMN payment_type VARCHAR(20)"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.debug("invoices.payment_type migration skipped: %s", e)

    # Add payment_type column to payments if missing
    try:
        db.session.execute(db.text(
            "ALTER TABLE payments ADD COLUMN payment_type VARCHAR(20) DEFAULT 'cash'"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.debug("payments.payment_type migration skipped: %s", e)

    # Add amount_sold column to payments if missing
    try:
        db.session.execute(db.text(
            "ALTER TABLE payments ADD COLUMN amount_sold NUMERIC(10,2) DEFAULT 0"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.debug("payments.amount_sold migration skipped: %s", e)

    # Create invoices, invoice_items, and notes tables if missing
    db.create_all()

    # Migrate old roles (sales, manager) to owner
    try:
        db.session.execute(db.text(
            "UPDATE users SET role = 'owner' WHERE role IN ('sales', 'manager')"
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.debug("Role migration skipped: %s", e)

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
            log.warning(
                "Default admin user created with auto-generated password: %s  "
                "Set ADMIN_PASSWORD env var and restart, or change via /change-password.",
                admin_password,
            )
        else:
            log.info("Default admin user created with ADMIN_PASSWORD from environment.")

    # Create demo user only if DEMO_ENABLED=true (opt-in)
    if os.environ.get("DEMO_ENABLED", "").lower() in ("true", "1", "yes"):
        if not User.query.filter_by(username="demo").first():
            demo = User(
                username="demo",
                email="demo@candyroute.local",
                role="demo",
                is_active=True,
            )
            demo_password = os.environ.get("DEMO_PASSWORD", "demo")
            demo.set_password(demo_password)
            db.session.add(demo)
            db.session.commit()
            log.info("Demo user created (username: demo, password: %s)",
                     "from DEMO_PASSWORD env var" if os.environ.get("DEMO_PASSWORD") else "demo (default)")
    else:
        # Deactivate demo user if it exists and DEMO_ENABLED is not set
        demo_user = User.query.filter_by(username="demo", role="demo").first()
        if demo_user and demo_user.is_active:
            demo_user.is_active = False
            db.session.commit()
            log.info("Demo user deactivated (set DEMO_ENABLED=true to re-enable)")

    # Add unique index on invoice_number (partial: non-NULL only)
    try:
        with db.engine.connect() as conn:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_invoices_invoice_number ON invoices (invoice_number) WHERE invoice_number IS NOT NULL"))
            conn.commit()
    except Exception as e:
        log.debug("Invoice number index creation skipped: %s", e)

    # Seed customers/leads from seed_data.json if table is empty
    _seed_customers()
