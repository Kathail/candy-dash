"""SQLAlchemy dialect adapter for libsql-client's DBAPI2 interface over Turso HTTP."""

from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite


class dialect(SQLiteDialect_pysqlite):
    """SQLite dialect that uses libsql_client.dbapi2 as the DBAPI driver."""

    name = "sqlite"
    driver = "libsql"
    supports_statement_cache = False

    @classmethod
    def dbapi(cls):
        from libsql_client import dbapi2
        return dbapi2

    @classmethod
    def import_dbapi(cls):
        from libsql_client import dbapi2
        return dbapi2

    def create_connect_args(self, url):
        # url looks like: sqlite+libsql:///https://host.turso.io?authToken=XXX
        # Extract the real URL from the database path
        db_path = str(url.database or "")
        query = dict(url.query)
        auth_token = query.pop("authToken", None)

        # Reconstruct the Turso URL, stripping any stray whitespace/newlines
        turso_url = db_path.strip()
        if auth_token:
            turso_url = f"{turso_url}?authToken={auth_token.strip()}"

        return [turso_url], {}

    def on_connect(self):
        # Skip pysqlite's on_connect which tries to set SQLite pragmas
        return None

    def do_ping(self, dbapi_connection):
        return True
