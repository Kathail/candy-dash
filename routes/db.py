"""
Database connection module.
...
"""

import os

import psycopg
from psycopg.rows import dict_row


def get_conn():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing! On Render: Check Environment tab or Blueprint attachment."
        )

    # Optional debug print for logs
    print(f"[DB DEBUG] Using DATABASE_URL: {database_url}")

    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=False,
    )
