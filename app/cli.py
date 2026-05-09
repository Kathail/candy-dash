"""Flask CLI commands."""

import os
from pathlib import Path

import click
from flask import Flask
from flask.cli import AppGroup

from app.mail import MailError, send_email


def register_cli(app: Flask) -> None:
    app.cli.add_command(_mail_group)
    app.cli.add_command(_backup_group)


_mail_group = AppGroup("mail", help="Email utilities.")


@_mail_group.command("send-test")
@click.option("--to", default=None, help="Recipient (defaults to BACKUP_EMAIL_TO env).")
def send_test(to: str | None) -> None:
    """Send a test email to verify Resend credentials work."""
    recipient = to or os.environ.get("BACKUP_EMAIL_TO")
    if not recipient:
        raise click.UsageError("Provide --to or set BACKUP_EMAIL_TO")
    try:
        msg_id = send_email(
            to=recipient,
            subject="Candy Dash test email",
            html="<p>Congrats on sending your <strong>first email</strong> from Candy Dash.</p>",
            text="Congrats on sending your first email from Candy Dash.",
        )
    except MailError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"Sent. Resend id: {msg_id}")


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
