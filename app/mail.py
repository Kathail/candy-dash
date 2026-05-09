"""Outbound email via Resend."""

import base64
import os
from typing import Iterable

import resend


class MailError(RuntimeError):
    """Raised when email config is missing or send fails."""


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise MailError(f"{key} is not set")
    return value


def send_email(
    *,
    to: str | Iterable[str],
    subject: str,
    html: str,
    text: str | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
) -> str:
    """Send an email via Resend. Returns the Resend message id.

    attachments: list of (filename, content_bytes) tuples.
    """
    resend.api_key = _require("RESEND_API_KEY")
    sender = _require("RESEND_FROM")
    recipients = [to] if isinstance(to, str) else list(to)

    payload: dict = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if attachments:
        payload["attachments"] = [
            {"filename": name, "content": base64.b64encode(content).decode("ascii")}
            for name, content in attachments
        ]

    try:
        result = resend.Emails.send(payload)
    except Exception as exc:
        raise MailError(f"Resend send failed: {exc}") from exc

    if isinstance(result, dict) and result.get("id"):
        return result["id"]
    raise MailError(f"Resend returned unexpected response: {result!r}")
