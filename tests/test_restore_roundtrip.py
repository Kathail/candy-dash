from decimal import Decimal

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


def test_restore_after_make_is_no_op(app, db, monkeypatch, tmp_path):
    import app.backup
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    from app.models import Customer
    _ensure_alembic(db)
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


def test_restore_replaces_current_data(app, db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    from app.models import Customer
    _ensure_alembic(db)
    db.session.add(Customer(name="Original"))
    db.session.commit()

    backup = make_backup()

    db.session.add(Customer(name="Added After Backup"))
    db.session.commit()

    restore_backup(backup)

    customers = db.session.query(Customer).all()
    assert len(customers) == 1
    assert customers[0].name == "Original"


def test_restore_preserves_decimal_precision(app, db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    from app.models import Customer
    _ensure_alembic(db)
    db.session.add(Customer(name="X", balance=Decimal("100.50")))
    db.session.commit()
    backup = make_backup()

    db.session.query(Customer).delete()
    db.session.commit()

    restore_backup(backup)

    c = db.session.query(Customer).one()
    assert c.balance == Decimal("100.50")
    assert str(c.balance) == "100.50"


def test_post_restore_inserts_dont_collide(app, db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    from app.models import Customer
    _ensure_alembic(db)
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


def test_restore_rotates_secret_key(app, db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.backup.SNAPSHOT_DIR", tmp_path)
    _ensure_alembic(db)
    backup = make_backup()
    before = app.secret_key
    restore_backup(backup)
    after = app.secret_key
    assert before != after
