#!/usr/bin/env python3
"""CLI: Full JSON import (with --clear option)."""

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal

from app import db, create_app
from app.models import User, Customer, RouteStop, Payment, ActivityLog


def parse_datetime(val):
    """Parse an ISO datetime string, return None if empty/None."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    # Handle both 'YYYY-MM-DDTHH:MM:SS' and 'YYYY-MM-DDTHH:MM:SS.ffffff'
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    # Try with timezone info (strip +00:00 suffix)
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        pass
    print(f"  Warning: could not parse datetime '{val}'")
    return None


def parse_date(val):
    """Parse an ISO date string."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        print(f"  Warning: could not parse date '{val}'")
        return None


def main():
    parser = argparse.ArgumentParser(description="Full JSON import from backup.")
    parser.add_argument("input_file", help="Path to the JSON file to import")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="DANGEROUS: Wipe all existing data before import",
    )
    args = parser.parse_args()

    # Load JSON first
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    app = create_app()

    with app.app_context():
        # Handle --clear
        if args.clear:
            confirm = input("WARNING: This will delete ALL existing data. Type 'yes' to confirm: ")
            if confirm.strip().lower() != "yes":
                print("Aborted.")
                sys.exit(0)

            print("Clearing existing data...")
            # Delete in reverse FK order
            ActivityLog.query.delete()
            Payment.query.delete()
            RouteStop.query.delete()
            Customer.query.delete()
            User.query.delete()
            db.session.commit()
            print("  All data cleared.")

        counts = {}

        # --- Users ---
        users_data = data.get("users", [])
        imported_users = 0
        skipped_users = 0
        existing_usernames = {u.username for u in User.query.all()}

        for u in users_data:
            if u.get("username") in existing_usernames:
                skipped_users += 1
                continue
            user = User(
                id=u.get("id"),
                username=u["username"],
                email=u.get("email"),
                password_hash=u.get("password_hash", "!imported-no-password"),
                role=u.get("role", "sales"),
                is_active=u.get("is_active", True),
            )
            db.session.add(user)
            existing_usernames.add(u["username"])
            imported_users += 1

        db.session.flush()
        counts["users"] = f"{imported_users} imported, {skipped_users} skipped (existing)"
        print(f"  Users: {counts['users']}")

        # --- Customers ---
        customers_data = data.get("customers", [])
        for c in customers_data:
            customer = Customer(
                id=c.get("id"),
                name=c["name"],
                address=c.get("address"),
                city=c.get("city"),
                phone=c.get("phone"),
                notes=c.get("notes"),
                balance=Decimal(str(c.get("balance", 0))),
                status=c.get("status", "active"),
                tax_exempt=c.get("tax_exempt", False),
                lead_source=c.get("lead_source"),
                created_at=parse_datetime(c.get("created_at")),
                updated_at=parse_datetime(c.get("updated_at")),
            )
            db.session.add(customer)
        db.session.flush()
        counts["customers"] = len(customers_data)
        print(f"  Customers: {counts['customers']}")

        # --- Route stops ---
        stops_data = data.get("route_stops", [])
        for s in stops_data:
            stop = RouteStop(
                id=s.get("id"),
                customer_id=s["customer_id"],
                route_date=parse_date(s.get("route_date")),
                sequence=s.get("sequence", 0),
                completed=s.get("completed", False),
                completed_at=parse_datetime(s.get("completed_at")),
                notes=s.get("notes"),
                created_by=s.get("created_by"),
            )
            db.session.add(stop)
        db.session.flush()
        counts["route_stops"] = len(stops_data)
        print(f"  Route stops: {counts['route_stops']}")

        # --- Payments ---
        payments_data = data.get("payments", [])
        for p in payments_data:
            payment = Payment(
                id=p.get("id"),
                customer_id=p["customer_id"],
                amount=Decimal(str(p.get("amount", 0))),
                payment_date=parse_datetime(p.get("payment_date")),
                receipt_number=p["receipt_number"],
                previous_balance=Decimal(str(p.get("previous_balance", 0))),
                notes=p.get("notes"),
                recorded_by=p.get("recorded_by"),
                created_at=parse_datetime(p.get("created_at")),
            )
            db.session.add(payment)
        db.session.flush()
        counts["payments"] = len(payments_data)
        print(f"  Payments: {counts['payments']}")

        # --- Activity logs ---
        logs_data = data.get("activity_logs", [])
        for l in logs_data:
            log = ActivityLog(
                id=l.get("id"),
                customer_id=l["customer_id"],
                user_id=l.get("user_id"),
                action=l["action"],
                description=l.get("description"),
                created_at=parse_datetime(l.get("created_at")),
            )
            db.session.add(log)
        db.session.flush()
        counts["activity_logs"] = len(logs_data)
        print(f"  Activity logs: {counts['activity_logs']}")

        db.session.commit()
        print("\nImport complete.")


if __name__ == "__main__":
    main()
