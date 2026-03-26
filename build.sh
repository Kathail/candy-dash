#!/usr/bin/env bash
set -o errexit

# Force clean venv — nuke any cached libsql/turso packages
pip install --upgrade pip
pip install -r requirements.txt

# Verify no libsql remnants
pip uninstall -y libsql-experimental libsql-client sqlalchemy-libsql 2>/dev/null || true

# Verify libsql_dialect.py is gone
rm -f app/libsql_dialect.py
