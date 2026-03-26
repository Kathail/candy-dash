#!/usr/bin/env python3
"""CLI: Deduplicate, normalize cities, clean phone numbers."""

import re
from collections import defaultdict
from decimal import Decimal

from app import db, create_app
from app.models import Customer


def normalize_name(name):
    """Strip, lowercase, collapse whitespace for duplicate detection."""
    return re.sub(r"\s+", " ", name.strip().lower())


def clean_phone(phone):
    """Extract digits only, format as (XXX) XXX-XXXX if 10 digits."""
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone  # Return original if not 10 digits


def main():
    app = create_app()

    with app.app_context():
        customers = Customer.query.order_by(Customer.id).all()

        if not customers:
            print("No customers found.")
            return

        cities_normalized = 0
        phones_cleaned = 0
        duplicates_merged = 0

        # --- Normalize cities ---
        for c in customers:
            if c.city:
                normalized = c.city.strip().title()
                if normalized != c.city:
                    c.city = normalized
                    cities_normalized += 1

        # --- Clean phone numbers ---
        for c in customers:
            if c.phone:
                cleaned = clean_phone(c.phone)
                if cleaned != c.phone:
                    c.phone = cleaned
                    phones_cleaned += 1

        # --- Deduplicate ---
        # Group customers by normalized name
        groups = defaultdict(list)
        for c in customers:
            groups[normalize_name(c.name)].append(c)

        for norm_name, group in groups.items():
            if len(group) < 2:
                continue

            # Keep the oldest (lowest id)
            group.sort(key=lambda c: c.id)
            keeper = group[0]

            for dup in group[1:]:
                # Sum balances
                keeper_bal = Decimal(str(keeper.balance or 0))
                dup_bal = Decimal(str(dup.balance or 0))
                keeper.balance = keeper_bal + dup_bal

                # Combine notes
                notes_parts = []
                if keeper.notes:
                    notes_parts.append(keeper.notes)
                if dup.notes:
                    notes_parts.append(dup.notes)
                if notes_parts:
                    keeper.notes = "\n".join(notes_parts)

                # Fill in missing fields from duplicate
                if not keeper.address and dup.address:
                    keeper.address = dup.address
                if not keeper.city and dup.city:
                    keeper.city = dup.city
                if not keeper.phone and dup.phone:
                    keeper.phone = dup.phone
                if not keeper.lead_source and dup.lead_source:
                    keeper.lead_source = dup.lead_source

                # Reassign related records to keeper
                for stop in dup.route_stops.all():
                    stop.customer_id = keeper.id
                for payment in dup.payments.all():
                    payment.customer_id = keeper.id
                for log in dup.activity_logs.all():
                    log.customer_id = keeper.id

                db.session.delete(dup)
                duplicates_merged += 1
                print(f"  Merged duplicate: '{dup.name}' (id={dup.id}) into '{keeper.name}' (id={keeper.id})")

        db.session.commit()

        print(f"\nCleanup complete:")
        print(f"  Cities normalized: {cities_normalized}")
        print(f"  Phones cleaned: {phones_cleaned}")
        print(f"  Duplicates merged: {duplicates_merged}")


if __name__ == "__main__":
    main()
