import csv
import os
import sys

import psycopg

CSV_PATH = "customers_backup.csv"
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set")
    sys.exit(1)

if not os.path.exists(CSV_PATH):
    print(f"ERROR: CSV file not found: {CSV_PATH}")
    sys.exit(1)


def normalize(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value if value else None


def main():
    print("Connecting to database...")
    conn = psycopg.connect(DATABASE_URL)
    cur = conn.cursor()

    inserted = 0
    skipped = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            name = normalize(row.get("Name"))
            address = normalize(row.get("Address"))
            phone = normalize(row.get("Phone"))
            website = normalize(row.get("Website"))

            notes_parts = []
            if normalize(row.get("Source")):
                notes_parts.append(f"Source: {row['Source']}")
            if normalize(row.get("Status")):
                notes_parts.append(f"Status: {row['Status']}")
            if normalize(row.get("Notes")):
                notes_parts.append(row["Notes"])

            notes = "\n".join(notes_parts) if notes_parts else None

            if not name:
                skipped += 1
                continue

            # basic dedupe: same name + address
            cur.execute(
                """
                SELECT id
                FROM customers
                WHERE name = %s AND address IS NOT DISTINCT FROM %s
                """,
                (name, address),
            )
            if cur.fetchone():
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO customers (name, address, phone, website, notes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (name, address, phone, website, notes),
            )
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print("Import complete.")
    print(f"Inserted: {inserted}")
    print(f"Skipped (duplicates / empty): {skipped}")


if __name__ == "__main__":
    main()
