"""SQLAlchemy dialect using libsql_experimental's native embedded replica connection."""

import os
import tempfile
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.pool import StaticPool


class dialect(SQLiteDialect_pysqlite):
    """SQLite dialect that connects to Turso via libsql_experimental's native driver.

    Uses an embedded replica (local SQLite file synced from Turso) which gives
    both fast local reads and durable remote storage.
    """

    name = "sqlite"
    driver = "libsql"
    supports_statement_cache = False

    # Store connection config at class level so create_connect_args can use it
    _turso_sync_url = None
    _turso_auth_token = None
    _local_db_path = None

    @classmethod
    def configure(cls, sync_url, auth_token, local_db_path=None):
        """Set Turso connection parameters before engine creation."""
        cls._turso_sync_url = sync_url.strip()
        cls._turso_auth_token = auth_token.strip()
        cls._local_db_path = local_db_path or os.path.join(
            tempfile.gettempdir(), "candy_route_replica.db"
        )

    @classmethod
    def dbapi(cls):
        import libsql_experimental as libsql
        return libsql

    @classmethod
    def import_dbapi(cls):
        import libsql_experimental as libsql
        return libsql

    def create_connect_args(self, url):
        return [], {}

    def connect(self, *cargs, **cparams):
        import libsql_experimental as libsql
        # Aggressively clean the auth token — Rust HTTP library rejects
        # any non-visible ASCII characters in header values
        raw_token = self._turso_auth_token or ""
        token = "".join(c for c in raw_token if 32 <= ord(c) < 127)
        sync_url = "".join(c for c in (self._turso_sync_url or "") if 32 <= ord(c) < 127)

        conn = libsql.connect(
            self._local_db_path,
            sync_url=sync_url,
            auth_token=token,
        )
        conn.sync()
        return conn

    def on_connect(self):
        return None

    def do_ping(self, dbapi_connection):
        return True

    def do_commit(self, dbapi_connection):
        dbapi_connection.commit()
        # Sync local changes to Turso after each commit
        try:
            dbapi_connection.sync()
        except Exception:
            pass

    @classmethod
    def get_pool_class(cls, url):
        # Use a single shared connection (embedded replica pattern)
        return StaticPool
