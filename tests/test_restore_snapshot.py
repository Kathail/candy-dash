import pytest

from app.backup import make_backup, restore_backup


def _ensure_alembic(db, head: str = "test_head") -> None:
    db.session.execute(db.text(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
    ))
    db.session.execute(db.text("DELETE FROM alembic_version"))
    db.session.execute(db.text(
        "INSERT INTO alembic_version (version_num) VALUES (:h)"
    ), {"h": head})
    db.session.commit()


def test_restore_creates_pre_restore_snapshot(app, db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    _ensure_alembic(db)

    backup = make_backup()
    assert list(tmp_path.iterdir()) == []

    restore_backup(backup)

    snapshots = list(tmp_path.glob("pre-restore-*.zip"))
    assert len(snapshots) == 1


def test_snapshot_retention_keeps_last_three(app, db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    _ensure_alembic(db)

    backup = make_backup()
    for _ in range(5):
        restore_backup(backup)

    snapshots = sorted(tmp_path.glob("pre-restore-*.zip"))
    assert len(snapshots) == 3


def test_snapshot_failure_aborts_restore(app, db, tmp_path, monkeypatch):
    """If snapshot can't be written, restore must not proceed."""
    from app.models import Customer
    _ensure_alembic(db)
    db.session.add(Customer(name="Original"))
    db.session.commit()

    backup = make_backup()

    db.session.add(Customer(name="Added After Backup"))
    db.session.commit()

    bad_dir = tmp_path / "blocking_file.txt"
    bad_dir.write_text("blocking")
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", bad_dir)

    with pytest.raises(Exception):
        restore_backup(backup)

    names = {c.name for c in db.session.query(Customer).all()}
    assert "Added After Backup" in names
