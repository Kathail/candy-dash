# routes/db.py
"""
Database connection module.
Provides a connection factory using psycopg for PostgreSQL.
Uses dict_row factory so queries return dicts (easier to work with).
"""

import os

import psycopg
from psycopg.rows import dict_row


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

    In production: Uses DATABASE_URL from environment (set by Render)
    In development: Defaults to local PostgreSQL database
    """
    # Use DATABASE_URL from environment (Render sets this automatically)
    # Falls back to local database for development
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://localhost/candy_route_planner"
    )

    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=False,
    )
