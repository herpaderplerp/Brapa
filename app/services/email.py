"""Email sending — stubbed behind an interface.

Dev impl logs instead of sending. A real provider (SES/Resend/SMTP) swaps in
here later without touching callers (mirrors storage.py local→S3).
"""
from __future__ import annotations

import logging

from app.models.notify import EMAIL_PREF_COLUMN

logger = logging.getLogger("brapa.email")


def send(to: str, subject: str, body: str) -> None:
    # Replace with a real provider later.
    logger.info("EMAIL → %s | %s | %s", to, subject, body)


def maybe_send(recipient, notif_type: str, subject: str, body: str) -> bool:
    """Send only if the recipient opted in for this notification type. Returns
    whether an email was sent."""
    col = EMAIL_PREF_COLUMN.get(notif_type)
    if not col or not recipient or not recipient.email:
        return False
    if not getattr(recipient, col, False):
        return False
    send(recipient.email, subject, body)
    return True
