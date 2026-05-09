# Backup & Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a restorable JSON-zip backup of the database, exposed via admin web UI and Flask CLI, with daily automation that emails the backup via Resend.

**Architecture:** Pure-Python backup module (`app/backup.py`) builds a zip of per-table JSON files plus a manifest. Restore validates schema match, takes a pre-restore snapshot, then atomically wipes and reloads inside a single transaction. Email goes through the existing `app/mail.py` Resend helper. Cron runs `flask backup now` from a Railway cron service.

**Tech Stack:** Python stdlib (zipfile, json, base64, smtplib via Resend SDK), Flask 3, SQLAlchemy 2, Click, pytest (newly introduced).

**Spec:** `docs/superpowers/specs/2026-05-09-backup-restore-design.md`

**Pre-existing scaffolding (already in repo, do not redo):**
- `app/mail.py` — `send_email(to, subject, html, text=, attachments=)` returns Resend message id, raises `MailError`.
- `app/cli.py` — already registers a `mail` Click group with `flask mail send-test`. Reuse the file by adding a new `backup` group.
- `requirements.txt` — already has `resend>=2.0`, `python-dotenv>=1.0`.
- `.env` — has `RESEND_API_KEY`, `RESEND_FROM`, `BACKUP_EMAIL_TO` for local dev.

---

## Task 1: Test infrastructure

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add pytest to requirements.txt**

Append after `python-dotenv>=1.0`:
```
pytest>=8.0
```

- [ ] **Step 2: Install pytest**

Run: `.venv/bin/pip install pytest`
Expected: `Successfully installed pytest-...`

- [ ] **Step 3: Create empty tests package**

Create `tests/__init__.py` with empty contents.

- [ ] **Step 4: Create conftest.py with app + db fixtures**

Create `tests/conftest.py`:
```python
"""Shared pytest fixtures."""

import os
import tempfile

import pytest

# Force test config before importing app
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture
def app():
    """Flask app bound to a fresh on-disk SQLite DB per test."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    from app import create_app, db as _db

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    with application.app_context():
        # init_db.init_database() already ran in create_app(); start clean.
        _db.session.remove()
        _db.drop_all()
        _db.create_all()
        yield application
        _db.session.remove()

    os.unlink(db_path)


@pytest.fixture
def db(app):
    """SQLAlchemy db bound to the test app."""
    from app import db as _db
    return _db
```

- [ ] **Step 5: Create smoke test**

Create `tests/test_smoke.py`:
```python
def test_app_boots(app):
    assert app is not None


def test_db_has_tables(app, db):
    tables = list(db.metadata.tables.keys())
    assert "customers" in tables
    assert "payments" in tables
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add tests/ requirements.txt
git commit -m "Add pytest scaffolding for backup/restore work"
```

---

## Task 2: JSON type-encoding helpers

**Files:**
- Create: `app/backup.py` (new module, will grow over the next tasks)
- Create: `tests/test_backup_encoding.py`

- [ ] **Step 1: Write failing tests for encode_value / decode_value**

Create `tests/test_backup_encoding.py`:
```python
from datetime import date, datetime, timezone
from decimal import Decimal

from app.backup import decode_value, encode_value


def test_int_roundtrip():
    assert encode_value(42) == 42
    assert decode_value(42) == 42


def test_string_roundtrip():
    assert encode_value("hello") == "hello"
    assert decode_value("hello") == "hello"


def test_none_roundtrip():
    assert encode_value(None) is None
    assert decode_value(None) is None


def test_bool_roundtrip():
    assert encode_value(True) is True
    assert decode_value(False) is False


def test_decimal_preserves_trailing_zeros():
    # Money MUST preserve "12.50" vs "12.5"
    assert encode_value(Decimal("12.50")) == "12.50"
    decoded = decode_value("12.50", target_type=Decimal)
    assert decoded == Decimal("12.50")
    assert str(decoded) == "12.50"


def test_decimal_zero():
    assert encode_value(Decimal("0.00")) == "0.00"
    assert decode_value("0.00", target_type=Decimal) == Decimal("0.00")


def test_datetime_roundtrip():
    dt = datetime(2026, 5, 9, 14, 30, 15, tzinfo=timezone.utc)
    encoded = encode_value(dt)
    assert encoded == "2026-05-09T14:30:15+00:00"
    decoded = decode_value(encoded, target_type=datetime)
    assert decoded == dt


def test_naive_datetime_roundtrip():
    dt = datetime(2026, 5, 9, 14, 30, 15)
    encoded = encode_value(dt)
    decoded = decode_value(encoded, target_type=datetime)
    assert decoded == dt


def test_date_roundtrip():
    d = date(2026, 5, 9)
    assert encode_value(d) == "2026-05-09"
    assert decode_value("2026-05-09", target_type=date) == d


def test_bytes_roundtrip():
    payload = b"\x00\x01\x02hello"
    encoded = encode_value(payload)
    assert encoded == {"__b64__": "AAECaGVsbG8="}
    assert decode_value(encoded, target_type=bytes) == payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_backup_encoding.py -v`
Expected: ImportError — `app.backup` does not yet exist.

- [ ] **Step 3: Implement encoding in `app/backup.py`**

Create `app/backup.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_backup_encoding.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backup.py tests/test_backup_encoding.py
git commit -m "Add JSON type encoding for backup format"
```

---

## Task 3: make_backup()

**Files:**
- Modify: `app/backup.py`
- Create: `tests/test_make_backup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_make_backup.py`:
```python
import io
import json
import zipfile
from datetime import date
from decimal import Decimal

from app.backup import make_backup


def test_make_backup_returns_bytes(app):
    result = make_backup()
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_make_backup_is_valid_zip(app):
    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names


def test_manifest_has_required_fields(app):
    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["format_version"] == 1
    assert manifest["app"] == "candy_dash"
    assert "created_at" in manifest
    assert "alembic_version" in manifest
    assert isinstance(manifest["tables"], list)


def test_manifest_lists_all_tables(app, db):
    expected = sorted(db.metadata.tables.keys())
    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    actual = sorted(t["name"] for t in manifest["tables"])
    assert actual == expected


def test_each_table_has_json_file(app, db):
    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        for table in db.metadata.tables:
            assert f"tables/{table}.json" in zf.namelist()


def test_table_files_contain_json_arrays(app):
    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        data = json.loads(zf.read("tables/customers.json"))
    assert isinstance(data, list)


def test_data_round_trips_through_zip(app, db):
    from app.models import Customer
    c = Customer(name="Test Co", balance=Decimal("12.50"))
    db.session.add(c)
    db.session.commit()

    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        rows = json.loads(zf.read("tables/customers.json"))

    assert len(rows) == 1
    assert rows[0]["name"] == "Test Co"
    assert rows[0]["balance"] == "12.50"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_make_backup.py -v`
Expected: ImportError — `make_backup` not defined in `app.backup`.

- [ ] **Step 3: Implement make_backup**

Append to `app/backup.py`:
```python
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
        result = db.session.execute(select(db.text("version_num"))
                                    .select_from(db.text("alembic_version"))).first()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_make_backup.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backup.py tests/test_make_backup.py
git commit -m "Implement make_backup() — JSON-zip of all tables"
```

---

## Task 4: Pre-flight validation for restore

**Files:**
- Modify: `app/backup.py`
- Create: `tests/test_restore_preflight.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_restore_preflight.py`:
```python
import io
import json
import zipfile
from io import BytesIO

import pytest

from app.backup import BackupError, make_backup, restore_backup


def _build_zip(manifest: dict, tables: dict[str, list]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, rows in tables.items():
            zf.writestr(f"tables/{name}.json", json.dumps(rows))
    return buf.getvalue()


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


def test_alembic_mismatch_raises(app):
    payload = _build_zip(
        {
            "format_version": 1,
            "app": "candy_dash",
            "alembic_version": "deadbeef0000",
            "tables": [],
        },
        {},
    )
    with pytest.raises(BackupError, match="schema"):
        restore_backup(payload)


def test_unknown_table_in_manifest_raises(app):
    # Build a zip claiming a table that doesn't exist in the model metadata
    from app.backup import _alembic_head
    head = _alembic_head()
    payload = _build_zip(
        {
            "format_version": 1,
            "app": "candy_dash",
            "alembic_version": head,
            "tables": [{"name": "imaginary_table", "rows": 0}],
        },
        {"imaginary_table": []},
    )
    with pytest.raises(BackupError, match="unknown table"):
        restore_backup(payload)


def test_zip_slip_protection(app):
    from app.backup import _alembic_head
    head = _alembic_head()
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format_version": 1, "app": "candy_dash",
            "alembic_version": head, "tables": []
        }))
        zf.writestr("../escape.json", "[]")
    with pytest.raises(BackupError, match="path"):
        restore_backup(buf.getvalue())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_restore_preflight.py -v`
Expected: ImportError on `BackupError` and `restore_backup`.

- [ ] **Step 3: Implement BackupError + pre-flight in restore_backup**

Append to `app/backup.py`:
```python
import re

VALID_TABLE_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


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
        table_name = name[len("tables/"):-len(".json")]
        if not VALID_TABLE_NAME.match(table_name):
            raise BackupError(f"Suspicious path in backup zip: {name!r}")


def _preflight(zip_bytes: bytes) -> tuple[zipfile.ZipFile, dict]:
    """Validate everything we can without touching the DB. Returns (zf, manifest)."""
    from app import db

    zf = _open_backup_zip(zip_bytes)
    _validate_zip_paths(zf)
    manifest = _read_manifest(zf)

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
    """Validate and restore a backup. Returns a summary dict."""
    zf, manifest = _preflight(zip_bytes)
    # Restore body comes in the next task.
    return {"validated": True, "tables": len(manifest.get("tables", []))}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_restore_preflight.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backup.py tests/test_restore_preflight.py
git commit -m "Add restore pre-flight validation (no DB writes)"
```

---

## Task 5: Restore transaction (delete + bulk insert + sequence reset)

**Files:**
- Modify: `app/backup.py`
- Create: `tests/test_restore_roundtrip.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_restore_roundtrip.py`:
```python
from decimal import Decimal

from app.backup import make_backup, restore_backup


def test_restore_after_make_is_no_op(app, db):
    from app.models import Customer
    db.session.add(Customer(name="A", balance=Decimal("1.00")))
    db.session.add(Customer(name="B", balance=Decimal("2.00")))
    db.session.commit()

    backup = make_backup()
    result = restore_backup(backup)

    assert result["restored"] is True
    customers = db.session.query(Customer).order_by(Customer.name).all()
    assert [c.name for c in customers] == ["A", "B"]
    assert customers[0].balance == Decimal("1.00")
    assert customers[1].balance == Decimal("2.00")


def test_restore_replaces_current_data(app, db):
    from app.models import Customer
    db.session.add(Customer(name="Original"))
    db.session.commit()

    backup = make_backup()

    db.session.add(Customer(name="Added After Backup"))
    db.session.commit()

    restore_backup(backup)

    customers = db.session.query(Customer).all()
    assert len(customers) == 1
    assert customers[0].name == "Original"


def test_restore_preserves_decimal_precision(app, db):
    from app.models import Customer
    db.session.add(Customer(name="X", balance=Decimal("100.50")))
    db.session.commit()
    backup = make_backup()

    db.session.query(Customer).delete()
    db.session.commit()

    restore_backup(backup)

    c = db.session.query(Customer).one()
    assert c.balance == Decimal("100.50")
    assert str(c.balance) == "100.50"


def test_post_restore_inserts_dont_collide(app, db):
    """After restore, new INSERTs must not reuse a restored ID."""
    from app.models import Customer
    db.session.add(Customer(name="A"))
    db.session.add(Customer(name="B"))
    db.session.add(Customer(name="C"))
    db.session.commit()
    max_id_before = db.session.query(Customer).order_by(Customer.id.desc()).first().id
    backup = make_backup()

    db.session.query(Customer).delete()
    db.session.commit()

    restore_backup(backup)

    new_c = Customer(name="New After Restore")
    db.session.add(new_c)
    db.session.commit()
    assert new_c.id > max_id_before


def test_restore_rotates_secret_key(app):
    """Restore must invalidate sessions by rotating the app secret."""
    backup = make_backup()
    before = app.secret_key
    restore_backup(backup)
    after = app.secret_key
    assert before != after
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_restore_roundtrip.py -v`
Expected: 4 failures — `restore_backup` returns `{"validated": True}` and doesn't actually restore.

- [ ] **Step 3: Implement the restore body**

Replace the existing `restore_backup` function in `app/backup.py` with:
```python
def restore_backup(zip_bytes: bytes) -> dict:
    """Validate and restore a backup atomically. Returns a summary dict."""
    from app import db

    zf, manifest = _preflight(zip_bytes)
    sorted_tables = list(db.metadata.sorted_tables)
    table_by_name = {t.name: t for t in sorted_tables}
    manifest_table_names = {entry["name"] for entry in manifest["tables"]}

    # Read all table data first so a JSON parse error doesn't half-wipe the DB.
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
        # Delete in reverse FK order
        for table in reversed(sorted_tables):
            db.session.execute(table.delete())

        # Insert in forward FK order
        for table in sorted_tables:
            if table.name not in manifest_table_names:
                continue  # Tables present in current models but not in backup stay empty
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
            return t.python_type  # Decimal when scale > 0, float otherwise
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
            # sqlite_sequence only exists if an AUTOINCREMENT column has been used.
            try:
                db.session.execute(
                    db.text(
                        "INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES (:n, :s)"
                    ),
                    {"n": table.name, "s": max_row},
                )
            except Exception:
                # Table without AUTOINCREMENT — nothing to reset.
                pass


def _invalidate_sessions() -> None:
    """Rotate the app secret to invalidate all active session cookies."""
    import secrets
    from flask import current_app
    try:
        current_app.secret_key = secrets.token_hex(32)
    except RuntimeError:
        # Outside an app context (shouldn't happen — restore is always inside one).
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_restore_roundtrip.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run all tests so far together to catch regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: all passing (smoke + encoding + make_backup + preflight + roundtrip).

- [ ] **Step 6: Commit**

```bash
git add app/backup.py tests/test_restore_roundtrip.py
git commit -m "Implement transactional restore with sequence reset"
```

---

## Task 6: Auto-snapshot before restore + retention

**Files:**
- Modify: `app/backup.py`
- Create: `tests/test_restore_snapshot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_restore_snapshot.py`:
```python
from pathlib import Path

from app.backup import make_backup, restore_backup


def test_restore_creates_pre_restore_snapshot(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)

    backup = make_backup()
    assert list(tmp_path.iterdir()) == []

    restore_backup(backup)

    snapshots = list(tmp_path.glob("pre-restore-*.zip"))
    assert len(snapshots) == 1


def test_snapshot_retention_keeps_last_three(app, tmp_path, monkeypatch):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)

    backup = make_backup()
    for _ in range(5):
        restore_backup(backup)

    snapshots = sorted(tmp_path.glob("pre-restore-*.zip"))
    assert len(snapshots) == 3


def test_snapshot_failure_aborts_restore(app, db, tmp_path, monkeypatch):
    """If snapshot can't be written, restore must not proceed."""
    from app.models import Customer
    db.session.add(Customer(name="Original"))
    db.session.commit()

    backup = make_backup()

    db.session.add(Customer(name="Added After Backup"))
    db.session.commit()

    # Point snapshot dir at a non-writable path
    bad_dir = tmp_path / "not_a_dir.txt"
    bad_dir.write_text("blocking file")
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", bad_dir)

    import pytest
    with pytest.raises(Exception):
        restore_backup(backup)

    # Original DB state preserved (the post-backup customer is still there)
    names = {c.name for c in db.session.query(Customer).all()}
    assert "Added After Backup" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_restore_snapshot.py -v`
Expected: 3 failures — no snapshot written.

- [ ] **Step 3: Add snapshot logic**

In `app/backup.py`:

(a) Add the imports and constants near the top of the file:
```python
from pathlib import Path

SNAPSHOT_DIR = Path("instance") / "backups"
SNAPSHOT_RETENTION = 3
```

(b) Add a helper:
```python
def _write_pre_restore_snapshot() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_bytes = make_backup()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SNAPSHOT_DIR / f"pre-restore-{timestamp}.zip"
    path.write_bytes(snapshot_bytes)

    snapshots = sorted(SNAPSHOT_DIR.glob("pre-restore-*.zip"))
    for old in snapshots[:-SNAPSHOT_RETENTION]:
        old.unlink()
    return path
```

(c) Insert a snapshot call at the top of `restore_backup`, BEFORE the try/except that does the destructive work:
```python
def restore_backup(zip_bytes: bytes) -> dict:
    from app import db

    zf, manifest = _preflight(zip_bytes)
    snapshot_path = _write_pre_restore_snapshot()  # NEW: before any DB writes
    sorted_tables = list(db.metadata.sorted_tables)
    # ... rest unchanged ...
```

And add `snapshot_path` to the returned summary:
```python
    return {
        "restored": True,
        "tables": len(manifest["tables"]),
        "rows": total_rows,
        "snapshot": str(snapshot_path),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_restore_snapshot.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add app/backup.py tests/test_restore_snapshot.py
git commit -m "Auto-snapshot before restore with last-3 retention"
```

---

## Task 7: email_backup()

**Files:**
- Modify: `app/backup.py`
- Create: `tests/test_email_backup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_email_backup.py`:
```python
import os

from app.backup import email_backup, make_backup


def test_email_backup_calls_send_email(app, monkeypatch):
    sent = {}

    def fake_send_email(*, to, subject, html, text=None, attachments=None):
        sent["to"] = to
        sent["subject"] = subject
        sent["html"] = html
        sent["text"] = text
        sent["attachments"] = attachments
        return "fake-message-id"

    monkeypatch.setattr("app.backup.send_email", fake_send_email)
    monkeypatch.setenv("BACKUP_EMAIL_TO", "test@example.com")

    backup = make_backup()
    email_backup(backup)

    assert sent["to"] == "test@example.com"
    assert "Candy Dash" in sent["subject"]
    assert sent["attachments"] is not None
    assert len(sent["attachments"]) == 1
    fname, content = sent["attachments"][0]
    assert fname.endswith(".zip")
    assert content == backup


def test_email_backup_supports_multiple_recipients(app, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "app.backup.send_email",
        lambda **kw: sent.update(kw) or "id"
    )
    monkeypatch.setenv("BACKUP_EMAIL_TO", "a@example.com, b@example.com")

    email_backup(make_backup())

    assert sent["to"] == ["a@example.com", "b@example.com"]


def test_email_backup_subject_includes_date(app, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "app.backup.send_email",
        lambda **kw: sent.update(kw) or "id"
    )
    monkeypatch.setenv("BACKUP_EMAIL_TO", "test@example.com")

    email_backup(make_backup())

    from datetime import date as _date
    assert _date.today().isoformat() in sent["subject"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_email_backup.py -v`
Expected: ImportError on `email_backup`.

- [ ] **Step 3: Implement email_backup**

Append to `app/backup.py`:
```python
import os

from app.mail import send_email


def email_backup(zip_bytes: bytes) -> str:
    """Email a backup zip via Resend. Returns the Resend message id."""
    recipients_raw = os.environ.get("BACKUP_EMAIL_TO", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        raise BackupError("BACKUP_EMAIL_TO is not set")

    today = datetime.now(timezone.utc).date().isoformat()

    # Recover counts from the just-built manifest
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    counts = {t["name"]: t["rows"] for t in manifest["tables"]}
    headline_parts = []
    for key in ("customers", "payments", "invoices"):
        if key in counts:
            headline_parts.append(f"{counts[key]} {key}")
    headline = " — " + ", ".join(headline_parts) if headline_parts else ""
    subject = f"[Candy Dash] Backup {today}{headline}"

    rows_table = "\n".join(f"  {n:<20} {c:>7}" for n, c in counts.items())
    body_text = (
        f"Candy Dash backup\n"
        f"Created: {manifest['created_at']}\n"
        f"Schema: {manifest['alembic_version']}\n\n"
        f"Tables:\n{rows_table}\n\n"
        f"To restore: open /admin/backups in the app and upload the attached zip.\n"
    )
    body_html = f"<pre style='font-family:monospace'>{body_text}</pre>"

    filename = f"candy_dash_backup_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}.zip"
    target = recipients[0] if len(recipients) == 1 else recipients

    return send_email(
        to=target,
        subject=subject,
        html=body_html,
        text=body_text,
        attachments=[(filename, zip_bytes)],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_email_backup.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/backup.py tests/test_email_backup.py
git commit -m "Add email_backup() — composes and sends backup via Resend"
```

---

## Task 8: CLI command `flask backup now`

**Files:**
- Modify: `app/cli.py`

- [ ] **Step 1: Add the command**

Open `app/cli.py`. Add at the top, after existing imports:
```python
from pathlib import Path
```

After the existing `_mail_group` and its `send_test` command, append:
```python
_backup_group = AppGroup("backup", help="Database backup utilities.")


@_backup_group.command("now")
@click.option("--no-email", is_flag=True, help="Build the zip but skip the email send.")
@click.option("--out", type=click.Path(), help="Also write the zip to this path.")
def backup_now(no_email: bool, out: str | None) -> None:
    """Generate a backup zip and email it."""
    from app.backup import email_backup, make_backup

    zip_bytes = make_backup()
    if out:
        Path(out).write_bytes(zip_bytes)
        click.echo(f"Wrote {out} ({len(zip_bytes):,} bytes)")
    if no_email:
        if not out:
            click.echo(f"Generated {len(zip_bytes):,} bytes (not emailed; use --out to save)")
        return
    msg_id = email_backup(zip_bytes)
    click.echo(f"Backup emailed. Resend id: {msg_id}")
```

Then register the new group inside `register_cli`:
```python
def register_cli(app: Flask) -> None:
    app.cli.add_command(_mail_group)
    app.cli.add_command(_backup_group)
```

- [ ] **Step 2: Smoke-test the CLI**

Run: `.venv/bin/flask backup now --no-email --out /tmp/cd-test-backup.zip`
Expected: `Wrote /tmp/cd-test-backup.zip (NNNN bytes)`. Verify zip is non-empty and contains `manifest.json`:
```bash
unzip -l /tmp/cd-test-backup.zip | head
```

- [ ] **Step 3: Commit**

```bash
git add app/cli.py
git commit -m "Add 'flask backup now' CLI command"
```

---

## Task 9: CLI command `flask backup restore`

**Files:**
- Modify: `app/cli.py`

- [ ] **Step 1: Add the command**

Append to `app/cli.py` inside the `_backup_group` (after `backup_now`):
```python
@_backup_group.command("restore")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option("--confirm", required=True, help="Type RESTORE to proceed.")
def backup_restore(path: str, confirm: str) -> None:
    """Restore the database from a backup zip. Destructive."""
    from app.backup import BackupError, restore_backup

    if confirm != "RESTORE":
        raise click.UsageError("--confirm must be exactly RESTORE (uppercase).")

    zip_bytes = Path(path).read_bytes()
    try:
        result = restore_backup(zip_bytes)
    except BackupError as exc:
        raise click.ClickException(str(exc))

    click.echo(
        f"Restored {result['rows']:,} rows across {result['tables']} tables. "
        f"Snapshot saved at {result['snapshot']}"
    )
```

- [ ] **Step 2: Smoke-test (using the zip from Task 8)**

Run: `.venv/bin/flask backup restore /tmp/cd-test-backup.zip --confirm RESTORE`
Expected: `Restored N rows across M tables. Snapshot saved at instance/backups/pre-restore-...zip`.

Run a wrong confirm: `.venv/bin/flask backup restore /tmp/cd-test-backup.zip --confirm yes`
Expected: usage error, exit non-zero, no DB changes.

- [ ] **Step 3: Commit**

```bash
git add app/cli.py
git commit -m "Add 'flask backup restore' CLI command"
```

---

## Task 10: Admin web routes

**Files:**
- Modify: `app/routes/admin.py`

- [ ] **Step 1: Add the three routes**

Open `app/routes/admin.py`. Locate the existing `# Backups` comment block (search for `# Backups`). Above the existing `@bp.route("/backups")` definition, add new imports if not already present:
```python
from werkzeug.utils import secure_filename
```

After the existing `/backups` route definition (the page route, before `backup_customers`), add:
```python
@bp.route("/backups/full-archive")
def backup_full_archive():
    """Download the full restorable backup zip."""
    from app.backup import make_backup
    from datetime import datetime, timezone
    zip_bytes = make_backup()
    filename = f"candy_dash_backup_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}.zip"
    return Response(
        zip_bytes,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/backups/email-now", methods=["POST"])
def backup_email_now():
    """Generate a backup and email it immediately."""
    from app.backup import email_backup, make_backup, BackupError
    try:
        zip_bytes = make_backup()
        msg_id = email_backup(zip_bytes)
    except BackupError as exc:
        flash(f"Email failed: {exc}", "error")
        return redirect(url_for("admin.backups"))
    except Exception as exc:
        flash(f"Email failed: {exc}", "error")
        return redirect(url_for("admin.backups"))
    flash(f"Backup emailed (Resend id: {msg_id}).", "success")
    return redirect(url_for("admin.backups"))


@bp.route("/backups/restore", methods=["POST"])
def backup_restore():
    """Restore the database from an uploaded backup zip."""
    from app.backup import restore_backup, BackupError

    confirm = request.form.get("confirm", "")
    if confirm != "RESTORE":
        flash("Restore aborted: confirmation phrase must be exactly RESTORE.", "warning")
        return redirect(url_for("admin.backups"))

    file = request.files.get("backup")
    if not file or not file.filename:
        flash("Restore aborted: no file uploaded.", "warning")
        return redirect(url_for("admin.backups"))

    safe = secure_filename(file.filename)
    if not safe.endswith(".zip"):
        flash("Restore aborted: file must be a .zip backup.", "warning")
        return redirect(url_for("admin.backups"))

    zip_bytes = file.read()
    try:
        result = restore_backup(zip_bytes)
    except BackupError as exc:
        flash(f"Restore failed: {exc}", "error")
        return redirect(url_for("admin.backups"))
    except Exception as exc:
        flash(f"Restore failed: {exc}", "error")
        return redirect(url_for("admin.backups"))

    flash(
        f"Restore complete: {result['rows']:,} rows across {result['tables']} tables. "
        f"Snapshot saved at {result['snapshot']}. Please log in again.",
        "success",
    )
    return redirect(url_for("admin.backups"))
```

- [ ] **Step 2: Run the dev server and verify routes register**

If the dev server is running, it auto-reloads. Otherwise:
```bash
.venv/bin/flask run --port 5000 &
```

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/admin/backups/full-archive`
Expected: `302` (redirect to login — proves the route is registered, auth is working).

Login as admin, then:
```bash
curl -s -c /tmp/cookies -X POST -F "username=admin" -F "password=admin123" http://localhost:5000/login
curl -s -b /tmp/cookies -o /tmp/dl.zip -w "%{http_code}\n" http://localhost:5000/admin/backups/full-archive
unzip -l /tmp/dl.zip | head
```
Expected: 200, zip contains `manifest.json`. (Login may need CSRF token — easier to do this part in browser.)

- [ ] **Step 3: Commit**

```bash
git add app/routes/admin.py
git commit -m "Add admin web routes for backup download/email/restore"
```

---

## Task 11: Admin template — Restorable Backup section

**Files:**
- Modify: `templates/admin/backups.html`

- [ ] **Step 1: Add the restorable section above the Full Backup section**

Open `templates/admin/backups.html`. After the closing `</div>` of the Stats grid (around line 30, after the route_stops card) and before the existing `{# -- Full Backup -- #}` comment, insert:

```html
  {# -- Restorable Backup -- #}
  <div class="flex items-center gap-2 pt-2 animate-fade-in-up">
    <div class="w-5 h-5 rounded-md bg-purple-500/15 flex items-center justify-center">
      <svg aria-hidden="true" class="w-3 h-3 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
      </svg>
    </div>
    <h2 class="text-xs font-bold text-purple-400 uppercase tracking-wider">Restorable Backup</h2>
    <div class="flex-1 h-px bg-gray-700"></div>
  </div>

  <div class="bg-panel rounded-xl border border-app p-4 space-y-3 animate-fade-in-up">
    <p class="text-xs text-gray-400">
      Full database snapshot as a single zip. Can be re-uploaded below to rebuild the database.
    </p>
    <div class="flex flex-wrap gap-2">
      <a href="{{ url_for('admin.backup_full_archive') }}"
         class="inline-flex items-center gap-2 px-3 py-2 bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 rounded-lg text-xs font-medium btn-press">
        Download zip
      </a>
      <form action="{{ url_for('admin.backup_email_now') }}" method="post" class="inline">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit"
                class="inline-flex items-center gap-2 px-3 py-2 bg-panel border border-app hover:border-purple-500/40 text-gray-200 rounded-lg text-xs font-medium btn-press">
          Email backup now
        </button>
      </form>
    </div>

    <details class="pt-2 border-t border-app">
      <summary class="cursor-pointer text-xs font-semibold text-red-400 hover:text-red-300">
        Restore from backup file (destructive)
      </summary>
      <form action="{{ url_for('admin.backup_restore') }}" method="post" enctype="multipart/form-data"
            class="mt-3 space-y-2"
            onsubmit="return confirm('This will replace ALL current data. Are you absolutely sure?');">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <p class="text-2xs text-gray-500">
          A pre-restore snapshot is automatically saved to <code>instance/backups/</code> in case you need to undo.
        </p>
        <input type="file" name="backup" accept=".zip" required
               class="block w-full text-xs text-gray-300 theme-input">
        <input type="text" name="confirm" placeholder="Type RESTORE to confirm" required
               pattern="RESTORE"
               class="block w-full text-xs theme-input">
        <button type="submit"
                class="inline-flex items-center gap-2 px-3 py-2 bg-red-500/15 hover:bg-red-500/25 text-red-300 rounded-lg text-xs font-medium btn-press">
          Restore database
        </button>
      </form>
    </details>
  </div>
```

- [ ] **Step 2: Visually verify in the dev server**

Open `http://localhost:5000/admin/backups` in a browser. You should see:
- The new "Restorable Backup" section above "Full Backup"
- "Download zip" and "Email backup now" buttons
- A collapsed "Restore from backup file (destructive)" details element
- The existing CSV downloads below, untouched

- [ ] **Step 3: Click "Download zip" — verify a zip downloads**

Click the button. A file `candy_dash_backup_<timestamp>.zip` should download. Inspect with `unzip -l`.

- [ ] **Step 4: Commit**

```bash
git add templates/admin/backups.html
git commit -m "Add Restorable Backup section to admin backups page"
```

---

## Task 12: End-to-end manual integration test

This task has no code; it's a runbook to execute against the dev server and document the result. Do not skip — it's the only test that exercises the full happy path through the UI.

- [ ] **Step 1: Restart dev server with a fresh DB**

Stop any running server. Delete the local SQLite file to start fresh:
```bash
rm -f /home/bb0rn/Documents/Projects/Candy-Dash/instance/candy_route.db
.venv/bin/flask run --port 5000 &
```

- [ ] **Step 2: Login as admin and seed test data**

In a browser, login as `admin` / `admin123`. Add 3 customers (any names). Record one payment for any customer.

- [ ] **Step 3: Download a backup**

Visit `/admin/backups`. Click "Download zip". Save the file as `~/cd-backup-test.zip`.

- [ ] **Step 4: Add divergent data**

Add 2 more customers. Database now has 5 customers; the backup has 3.

- [ ] **Step 5: Restore from the backup**

On `/admin/backups`, expand "Restore from backup file". Upload `~/cd-backup-test.zip`, type `RESTORE`, click Restore database. Confirm the JS confirm dialog.

- [ ] **Step 6: Verify post-restore state**

After flash message, log in again (session was invalidated). Visit Customers — should see 3 customers (the originals), not 5. Payment should still exist on the same customer.

- [ ] **Step 7: Verify auto-snapshot**

```bash
ls -la instance/backups/
```
Expected: `pre-restore-*.zip` files exist.

- [ ] **Step 8: Verify post-restore inserts work**

In the UI, add a new customer. Should succeed without PK collision. Check the customer's id is greater than max restored id.

- [ ] **Step 9: Test schema-mismatch refusal**

Create a manually-corrupted manifest:
```bash
cd /tmp && rm -rf bad-backup && mkdir bad-backup && cd bad-backup
unzip ~/cd-backup-test.zip
python3 -c "import json,sys; m=json.load(open('manifest.json')); m['alembic_version']='deadbeef'; json.dump(m,open('manifest.json','w'))"
zip -r ../bad-backup.zip .
```
In `/admin/backups`, upload `bad-backup.zip` with `RESTORE` confirmation. Expected: error flash mentioning schema mismatch. DB unchanged.

- [ ] **Step 10: Test email path end-to-end**

```bash
.venv/bin/flask backup now
```
Expected: `Backup emailed. Resend id: ...`. Check `kyle.cahill@pm.me` for the email with attached zip.

- [ ] **Step 11: Document the integration test in a brief note**

(No commit needed; just confirm everything in steps 6, 7, 8, 9, 10 worked as expected before declaring the implementation complete.)

---

## Out of plan scope (handled separately, with user permission)

- **Railway cron service setup.** Once the implementation is committed and tested locally, run `railway` CLI to (1) set the env vars `RESEND_API_KEY`, `RESEND_FROM`, `BACKUP_EMAIL_TO` on the production service, (2) add a new cron-type service running `flask backup now` on schedule `0 7 * * *` UTC. Verify the first cron run by watching for the email.
- **Domain verification in Resend.** Switching `RESEND_FROM` from `onboarding@resend.dev` to a verified `northernsweetsupply.ca` address improves deliverability. Out of scope here.
- **`git push`.** App is live; pushing requires explicit user OK.
