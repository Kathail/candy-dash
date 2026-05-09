import io
import json
import zipfile
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


def test_alembic_head_in_manifest_when_set(app, db):
    """Schema marker must be captured when alembic_version table has a row."""
    db.session.execute(
        db.text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
    )
    db.session.execute(db.text("DELETE FROM alembic_version"))
    db.session.execute(
        db.text("INSERT INTO alembic_version (version_num) VALUES ('test_head_abc123')")
    )
    db.session.commit()

    import io, json, zipfile
    result = make_backup()
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["alembic_version"] == "test_head_abc123"
