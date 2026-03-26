#!/usr/bin/env bash
set -o errexit

# Force clean venv — nuke any cached libsql/turso packages
pip install --upgrade pip
pip install -r requirements.txt

# Verify no libsql remnants
pip uninstall -y libsql-experimental libsql-client sqlalchemy-libsql 2>/dev/null || true

# Nuke all Turso/libsql remnants
rm -f app/libsql_dialect.py
rm -f /tmp/candy_route_replica.db*
rm -f candy_route_replica.db*
rm -f *.db *.db-shm *.db-wal *.db-info
find /tmp -name "candy_route*" -delete 2>/dev/null || true
