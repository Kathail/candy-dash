# routes/db.py
"""
Database connection module.
Provides a connection factory using psycopg for PostgreSQL.
Uses dict_row factory so queries return dicts (easier to work with).
"""

import os

import psycopg
from psycopg.rows import dict_row

# Load from environment (required for security/portability)
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Example: export DATABASE_URL=postgresql://user:pass@localhost:5432/dbname"
    )


def get_conn():
    """
    Returns a new psycopg connection with:
    - dict_row factory (fetchone/fetchall return dicts)
    - autocommit=False (we manage transactions explicitly)

    Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
                conn.commit()   # or conn.rollback()
    """
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        autocommit=False,
    )
