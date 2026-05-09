def test_app_boots(app):
    assert app is not None


def test_db_has_tables(app, db):
    tables = list(db.metadata.tables.keys())
    assert "customers" in tables
    assert "payments" in tables
