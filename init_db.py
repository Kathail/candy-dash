# init_db.py   ── FULL FILE (updated import)
import os
import sys

import psycopg

# Debug: confirm where we are and what Python sees
print("Current working directory:", os.getcwd())
print("Python executable:", sys.executable)
print("sys.path first few entries:", sys.path[:4])

try:
    from routes.db import get_conn  # ← this is the fixed import

    print("SUCCESS: Imported get_conn from routes.db")
except ImportError as e:
    print("IMPORT FAILED:", str(e))
    print(
        "Files in ./routes/:",
        os.listdir("routes")
        if os.path.exists("routes")
        else "routes/ folder not found",
    )
    sys.exit(1)


def init_db():
    project_root = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(project_root, "schema.sql")

    print("Looking for schema.sql at:", schema_path)

    if not os.path.exists(schema_path):
        print("ERROR: schema.sql not found in project root")
        return

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
                conn.commit()
        print("✅ Database schema created successfully.")
        print(
            "Tables should now exist (customers, routes, route_stops, visits, payments)"
        )
    except psycopg.Error as e:
        print("PostgreSQL error:")
        print(e.pgerror if hasattr(e, "pgerror") else str(e))
    except Exception as e:
        print("Unexpected error during schema execution:", str(e))


if __name__ == "__main__":
    init_db()
