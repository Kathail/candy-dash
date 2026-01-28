def get_conn():
    """
    Returns a new psycopg connection...
    """
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        # In production (Render), this should never happen if DB is attached
        # Raise clear error so logs show the issue immediately
        raise ValueError(
            "DATABASE_URL environment variable is missing or empty. "
            "On Render: Check dashboard → candy-dash service → Environment tab. "
            "It should be auto-set from the attached PostgreSQL DB."
        )

    # Optional debug print (visible in Render logs) - remove after testing
    print(f"[DB] Connecting using: {database_url}")

    return psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=False,
    )
