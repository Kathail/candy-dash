#!/usr/bin/env python3
"""CLI: Full JSON export for backup/migration."""

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal

from app import db, create_app
from app.models import User, Customer, RouteStop, Payment, ActivityLog


class ExportEncoder(json.JSONEncoder):
    """Handle Decimal, datetime, and date serialization."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def row_to_dict(obj, exclude=None):
    """Convert a SQLAlchemy model instance to a dict."""
    exclude = exclude or set()
    data = {}
    for col in obj.__table__.columns:
        if col.name not in exclude:
            data[col.name] = getattr(obj, col.name)
    return data


def main():
    parser = argparse.ArgumentParser(description="Full JSON export for backup/migration.")
    parser.add_argument("output_file", help="Path for the output JSON file")
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        export = {}

        # Users (without password_hash)
        users = User.query.order_by(User.id).all()
        export["users"] = [row_to_dict(u, exclude={"password_hash"}) for u in users]
        print(f"  Users: {len(export['users'])}")

        # Customers
        customers = Customer.query.order_by(Customer.id).all()
        export["customers"] = [row_to_dict(c) for c in customers]
        print(f"  Customers: {len(export['customers'])}")

        # Route stops
        stops = RouteStop.query.order_by(RouteStop.id).all()
        export["route_stops"] = [row_to_dict(s) for s in stops]
        print(f"  Route stops: {len(export['route_stops'])}")

        # Payments
        payments = Payment.query.order_by(Payment.id).all()
        export["payments"] = [row_to_dict(p) for p in payments]
        print(f"  Payments: {len(export['payments'])}")

        # Activity logs
        logs = ActivityLog.query.order_by(ActivityLog.id).all()
        export["activity_logs"] = [row_to_dict(l) for l in logs]
        print(f"  Activity logs: {len(export['activity_logs'])}")

        try:
            with open(args.output_file, "w", encoding="utf-8") as f:
                json.dump(export, f, cls=ExportEncoder, indent=2, ensure_ascii=False)
            print(f"\nExported to: {args.output_file}")
        except Exception as e:
            print(f"Error writing file: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
