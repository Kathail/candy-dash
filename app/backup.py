"""Backup and restore for the application database."""

from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal
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
