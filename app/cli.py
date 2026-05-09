"""Flask CLI commands."""

import os

import click
from flask import Flask
from flask.cli import AppGroup

from app.mail import MailError, send_email


def register_cli(app: Flask) -> None:
    app.cli.add_command(_mail_group)


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
