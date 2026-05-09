from app.backup import email_backup, make_backup


def _ensure_alembic(db, head: str = "test_head") -> None:
    db.session.execute(db.text(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
    ))
    db.session.execute(db.text("DELETE FROM alembic_version"))
    db.session.execute(db.text(
        "INSERT INTO alembic_version (version_num) VALUES (:h)"
    ), {"h": head})
    db.session.commit()


def test_email_backup_calls_send_email(app, db, monkeypatch):
    _ensure_alembic(db)
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


def test_email_backup_supports_multiple_recipients(app, db, monkeypatch):
    _ensure_alembic(db)
    sent = {}
    monkeypatch.setattr(
        "app.backup.send_email",
        lambda **kw: sent.update(kw) or "id"
    )
    monkeypatch.setenv("BACKUP_EMAIL_TO", "a@example.com, b@example.com")

    email_backup(make_backup())

    assert sent["to"] == ["a@example.com", "b@example.com"]


def test_email_backup_subject_includes_date(app, db, monkeypatch):
    _ensure_alembic(db)
    sent = {}
    monkeypatch.setattr(
        "app.backup.send_email",
        lambda **kw: sent.update(kw) or "id"
    )
    monkeypatch.setenv("BACKUP_EMAIL_TO", "test@example.com")

    email_backup(make_backup())

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    assert today in sent["subject"]
