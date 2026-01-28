import os

import psycopg
from psycopg.rows import dict_row

# Render provides DATABASE_URL automatically if linked,
# or you can set it manually in the Web Service environment.
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it in Render Environment Variables."
    )


def get_conn():
    """
    Returns a new PostgreSQL connection.
    Uses dict_row so cursors return dict-like rows.
    """
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=5,
    )
