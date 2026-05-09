"""Backup and restore for the application database."""

from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


def encode_value(value: Any) -> Any:
    """Encode a Python value for JSON storage in a backup."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, float):
        return value
    raise TypeError(f"Cannot encode value of type {type(value).__name__}")


def decode_value(value: Any, *, target_type: type | None = None) -> Any:
    """Decode a JSON value back into the target Python type."""
    if value is None:
        return None
    if isinstance(value, dict) and "__b64__" in value:
        return base64.b64decode(value["__b64__"])
    if target_type is Decimal:
        return Decimal(str(value))
    if target_type is datetime:
        return datetime.fromisoformat(value)
    if target_type is date:
        return date.fromisoformat(value)
    if target_type is bytes:
        if isinstance(value, dict) and "__b64__" in value:
            return base64.b64decode(value["__b64__"])
        return bytes(value)
    return value


import io
import json
import zipfile
from datetime import datetime, timezone

from sqlalchemy import select


def _row_to_dict(row, table) -> dict:
    return {col.name: encode_value(getattr(row, col.name, None)) for col in table.columns}


def _alembic_head() -> str | None:
    from app import db
    try:
        result = db.session.execute(
            db.text("SELECT version_num FROM alembic_version")
        ).first()
        return result[0] if result else None
    except Exception:
        return None


def make_backup() -> bytes:
    """Build a full restorable backup of the database. Returns zip bytes."""
    from app import db

    sorted_tables = list(db.metadata.sorted_tables)
    table_data: dict[str, list[dict]] = {}

    for table in sorted_tables:
        rows = db.session.execute(table.select()).mappings().all()
        table_data[table.name] = [
            {k: encode_value(v) for k, v in dict(row).items()} for row in rows
        ]

    manifest = {
        "format_version": 1,
        "app": "candy_dash",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "alembic_version": _alembic_head(),
        "tables": [{"name": t.name, "rows": len(table_data[t.name])} for t in sorted_tables],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for table in sorted_tables:
            zf.writestr(
                f"tables/{table.name}.json",
                json.dumps(table_data[table.name], indent=2),
            )
    return buf.getvalue()


import re

VALID_TABLE_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

SNAPSHOT_DIR = Path("instance") / "backups"
SNAPSHOT_RETENTION = 3


class BackupError(RuntimeError):
    """Raised when a backup is malformed, incompatible, or restore fails."""


def _open_backup_zip(zip_bytes: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise BackupError(f"Not a valid zip file: {exc}") from exc


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    if "manifest.json" not in zf.namelist():
        raise BackupError("Backup zip is missing manifest.json")
    try:
        return json.loads(zf.read("manifest.json"))
    except json.JSONDecodeError as exc:
        raise BackupError(f"manifest.json is not valid JSON: {exc}") from exc


def _validate_zip_paths(zf: zipfile.ZipFile) -> None:
    for name in zf.namelist():
        if name == "manifest.json":
            continue
        if not name.startswith("tables/") or "/" in name[len("tables/"):]:
            raise BackupError(f"Suspicious path in backup zip: {name!r}")
        if not name.endswith(".json"):
            raise BackupError(f"Suspicious path in backup zip: {name!r}")
        table_name = name[len("tables/"):-len(".json")]
        if not VALID_TABLE_NAME.match(table_name):
            raise BackupError(f"Suspicious path in backup zip: {name!r}")


def _preflight(zip_bytes: bytes) -> tuple[zipfile.ZipFile, dict]:
    """Validate everything we can without touching the DB. Returns (zf, manifest)."""
    from app import db

    zf = _open_backup_zip(zip_bytes)
    manifest = _read_manifest(zf)
    _validate_zip_paths(zf)

    if manifest.get("format_version") != 1:
        raise BackupError(
            f"Unsupported backup format_version: {manifest.get('format_version')!r}"
        )

    backup_head = manifest.get("alembic_version")
    current_head = _alembic_head()
    if backup_head != current_head:
        raise BackupError(
            f"Schema mismatch: backup is from {backup_head!r}, current is {current_head!r}. "
            f"Apply migrations to match before restoring."
        )

    known_tables = set(db.metadata.tables.keys())
    for entry in manifest.get("tables", []):
        if entry["name"] not in known_tables:
            raise BackupError(f"Manifest references unknown table: {entry['name']!r}")

    return zf, manifest


def restore_backup(zip_bytes: bytes) -> dict:
    """Validate and restore a backup atomically. Returns a summary dict."""
    from app import db

    zf, manifest = _preflight(zip_bytes)
    snapshot_path = _write_pre_restore_snapshot()
    sorted_tables = list(db.metadata.sorted_tables)
    manifest_table_names = {entry["name"] for entry in manifest["tables"]}

    parsed: dict[str, list[dict]] = {}
    for entry in manifest["tables"]:
        name = entry["name"]
        path = f"tables/{name}.json"
        if path not in zf.namelist():
            raise BackupError(f"Manifest lists {name!r} but {path} is missing from zip")
        try:
            parsed[name] = json.loads(zf.read(path))
        except json.JSONDecodeError as exc:
            raise BackupError(f"{path} is not valid JSON: {exc}") from exc

    total_rows = 0
    try:
        for table in reversed(sorted_tables):
            db.session.execute(table.delete())

        for table in sorted_tables:
            if table.name not in manifest_table_names:
                continue
            rows = parsed[table.name]
            if not rows:
                continue
            decoded = [_decode_row(row, table) for row in rows]
            db.session.execute(table.insert(), decoded)
            total_rows += len(decoded)

        _reset_sequences(sorted_tables)

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    _invalidate_sessions()

    return {
        "restored": True,
        "tables": len(manifest["tables"]),
        "rows": total_rows,
        "snapshot": str(snapshot_path),
    }


def _decode_row(row: dict, table) -> dict:
    out = {}
    for col in table.columns:
        if col.name not in row:
            continue
        raw = row[col.name]
        target = _python_type_for_column(col)
        out[col.name] = decode_value(raw, target_type=target)
    return out


def _python_type_for_column(col):
    """Best-effort mapping from SQLAlchemy column type to Python target type."""
    from sqlalchemy import Date, DateTime, LargeBinary, Numeric
    t = col.type
    if isinstance(t, Numeric):
        try:
            return t.python_type
        except NotImplementedError:
            return None
    if isinstance(t, DateTime):
        return datetime
    if isinstance(t, Date):
        return date
    if isinstance(t, LargeBinary):
        return bytes
    return None


def _reset_sequences(tables) -> None:
    """Bump auto-increment sequences past the max restored ID."""
    from app import db
    dialect = db.engine.dialect.name

    for table in tables:
        pk_cols = [c for c in table.primary_key.columns if c.autoincrement]
        if not pk_cols:
            continue
        pk = pk_cols[0]

        if dialect == "postgresql":
            db.session.execute(db.text(
                f"SELECT setval(pg_get_serial_sequence(:tbl, :col), "
                f"GREATEST((SELECT COALESCE(MAX({pk.name}), 0) FROM {table.name}), 1))"
            ), {"tbl": table.name, "col": pk.name})
        elif dialect == "sqlite":
            max_row = db.session.execute(
                db.text(f"SELECT MAX({pk.name}) FROM {table.name}")
            ).scalar()
            if not max_row:
                continue
            try:
                db.session.execute(
                    db.text(
                        "INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES (:n, :s)"
                    ),
                    {"n": table.name, "s": max_row},
                )
            except Exception:
                pass


def _invalidate_sessions() -> None:
    """Rotate the app secret to invalidate all active session cookies."""
    import secrets
    from flask import current_app
    try:
        current_app.secret_key = secrets.token_hex(32)
    except RuntimeError:
        pass


def _write_pre_restore_snapshot() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_bytes = make_backup()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = SNAPSHOT_DIR / f"pre-restore-{timestamp}.zip"
    path.write_bytes(snapshot_bytes)

    snapshots = sorted(SNAPSHOT_DIR.glob("pre-restore-*.zip"))
    for old in snapshots[:-SNAPSHOT_RETENTION]:
        old.unlink()
    return path
