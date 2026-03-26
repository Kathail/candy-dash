#!/usr/bin/env python3
"""CLI: Bulk lead import from CSV."""

import argparse
import csv
import re
import sys

from app import db, create_app
from app.models import Customer


def normalize_name(name):
    """Strip, lowercase, collapse whitespace for duplicate detection."""
    return re.sub(r"\s+", " ", name.strip().lower())


def main():
    parser = argparse.ArgumentParser(description="Bulk lead import from CSV.")
    parser.add_argument("csv_file", help="Path to the CSV file to import")
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
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

                    try:
                        customer = Customer(
                            name=name,
                            address=(row.get("address") or "").strip() or None,
                            city=(row.get("city") or "").strip() or None,
                            phone=(row.get("phone") or "").strip() or None,
                            notes=(row.get("notes") or "").strip() or None,
                            lead_source=(row.get("lead_source") or "").strip() or None,
                            balance=0,
                            status="lead",
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

        print(f"\nLead import complete:")
        print(f"  Imported: {imported}")
        print(f"  Skipped (duplicates): {skipped}")
        print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
