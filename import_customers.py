#!/usr/bin/env python3
"""CLI: Bulk customer import from CSV."""

import argparse
import csv
import re
import sys
from decimal import Decimal, InvalidOperation

from app import db, create_app
from app.models import Customer


def normalize_name(name):
    """Strip, lowercase, collapse whitespace for duplicate detection."""
    return re.sub(r"\s+", " ", name.strip().lower())


def main():
    parser = argparse.ArgumentParser(description="Bulk customer import from CSV.")
    parser.add_argument("csv_file", nargs="?", help="Path to the CSV file to import")
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Wipe all customer data without importing",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        default=True,
        help="Append mode - do not clear existing data (default)",
    )
    args = parser.parse_args()

    if not args.clear_only and not args.csv_file:
        parser.error("csv_file is required unless --clear-only is specified")

    app = create_app()

    with app.app_context():
        if args.clear_only:
            count = Customer.query.count()
            Customer.query.delete()
            db.session.commit()
            print(f"Cleared {count} customers.")
            return

        # Build set of existing normalized names for duplicate detection
        existing_names = set()
        for c in Customer.query.all():
            existing_names.add(normalize_name(c.name))

        imported = 0
        skipped = 0
        errors = 0

        try:
            with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)

                # Validate required column
                if "name" not in (reader.fieldnames or []):
                    print("Error: CSV must have a 'name' column.", file=sys.stderr)
                    sys.exit(1)

                for line_num, row in enumerate(reader, start=2):
                    name = (row.get("name") or "").strip()
                    if not name:
                        print(f"  Line {line_num}: skipped - empty name")
                        errors += 1
                        continue

                    norm = normalize_name(name)
                    if norm in existing_names:
                        print(f"  Line {line_num}: skipped duplicate - {name}")
                        skipped += 1
                        continue

                    # Parse balance
                    balance = Decimal("0")
                    raw_balance = (row.get("balance") or "").strip()
                    if raw_balance:
                        try:
                            balance = Decimal(raw_balance.replace(",", ""))
                        except InvalidOperation:
                            print(f"  Line {line_num}: invalid balance '{raw_balance}', using 0")

                    try:
                        customer = Customer(
                            name=name,
                            address=(row.get("address") or "").strip() or None,
                            city=(row.get("city") or "").strip() or None,
                            phone=(row.get("phone") or "").strip() or None,
                            notes=(row.get("notes") or "").strip() or None,
                            balance=balance,
                            status="active",
                        )
                        db.session.add(customer)
                        existing_names.add(norm)
                        imported += 1
                    except Exception as e:
                        print(f"  Line {line_num}: error - {e}")
                        errors += 1

                db.session.commit()

        except FileNotFoundError:
            print(f"Error: File not found: {args.csv_file}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error reading CSV: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"\nImport complete:")
        print(f"  Imported: {imported}")
        print(f"  Skipped (duplicates): {skipped}")
        print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
