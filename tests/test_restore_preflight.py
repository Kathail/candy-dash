import json
import zipfile
from io import BytesIO

import pytest

from app.backup import BackupError, restore_backup


def _build_zip(manifest: dict, tables: dict[str, list]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, rows in tables.items():
            zf.writestr(f"tables/{name}.json", json.dumps(rows))
    return buf.getvalue()


def _ensure_alembic(db, head: str) -> None:
    """Create alembic_version table if missing and seed it with head."""
    db.session.execute(db.text(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
    ))
    db.session.execute(db.text("DELETE FROM alembic_version"))
    db.session.execute(db.text(
        "INSERT INTO alembic_version (version_num) VALUES (:h)"
    ), {"h": head})
    db.session.commit()


def test_corrupt_zip_raises(app):
    with pytest.raises(BackupError, match="zip"):
        restore_backup(b"not a zip file")


def test_missing_manifest_raises(app):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("random.json", "{}")
    with pytest.raises(BackupError, match="manifest"):
        restore_backup(buf.getvalue())


def test_unknown_format_version_raises(app):
    payload = _build_zip(
        {"format_version": 99, "app": "candy_dash", "alembic_version": None, "tables": []},
        {},
    )
    with pytest.raises(BackupError, match="format"):
        restore_backup(payload)


def test_alembic_mismatch_raises(app, db):
    _ensure_alembic(db, "current_head")
    payload = _build_zip(
        {
            "format_version": 1,
            "app": "candy_dash",
            "alembic_version": "deadbeef0000",
            "tables": [],
        },
        {},
    )
    with pytest.raises(BackupError, match="schema|chema"):
        restore_backup(payload)


def test_unknown_table_in_manifest_raises(app, db):
    from app.backup import _alembic_head
    _ensure_alembic(db, "test_head")
    payload = _build_zip(
        {
            "format_version": 1,
            "app": "candy_dash",
            "alembic_version": "test_head",
            "tables": [{"name": "imaginary_table", "rows": 0}],
        },
        {"imaginary_table": []},
    )
    with pytest.raises(BackupError, match="unknown table"):
        restore_backup(payload)


def test_zip_slip_protection(app, db):
    _ensure_alembic(db, "test_head")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format_version": 1, "app": "candy_dash",
            "alembic_version": "test_head", "tables": []
        }))
        zf.writestr("../escape.json", "[]")
    with pytest.raises(BackupError, match="path"):
        restore_backup(buf.getvalue())
