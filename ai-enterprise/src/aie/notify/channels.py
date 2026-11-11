"""Kanalerna: ntfy (push till mobilen) och Gmail SMTP (e-post). Bara standardbiblioteket."""
from __future__ import annotations

import os
import smtplib
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage

from ..monitoring import get_logger

log = get_logger("notify")
NTFY_URL = "https://ntfy.sh/"
SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
TIMEOUT = 15


def send_ntfy(topic: str, title: str, message: str, opener=urllib.request.urlopen) -> None:
    """Push via ntfy.sh. Ämnet är hemligt (slumpat), eftersom den som kan ämnet kan läsa notiserna.
    Därför skickas bara generisk text hit, aldrig belopp eller namn (D-091)."""
    request = urllib.request.Request(NTFY_URL + topic, data=message.encode("utf-8"), method="POST",
                                     headers={"Title": title, "Tags": "bell"})
    with opener(request, timeout=TIMEOUT) as res:
        if res.status >= 300:
            raise OSError(f"ntfy svarade {res.status}")


def send_email(user: str, password: str, to: list[str], subject: str, body: str, smtp=smtplib.SMTP_SSL) -> None:
    message = EmailMessage()
    message["From"] = user
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    with smtp(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as server:
        server.login(user, password)
        server.send_message(message)


@dataclass
class Channels:
    """Det som är konfigurerat i miljön. En kanal utan hemligheter hoppas över utan fel."""

    ntfy_topic: str = ""
    gmail_user: str = ""
    gmail_password: str = ""
    recipients: tuple[str, ...] = ()
    opener: object = urllib.request.urlopen
    smtp: object = smtplib.SMTP_SSL

    @classmethod
    def from_env(cls, environ=os.environ) -> "Channels":
        from ..dashboard.control import parse_emails

        user = environ.get("GMAIL_USER", "").strip()
        recipients = tuple(sorted(parse_emails(environ.get("ALLOWED_EMAILS")))) or ((user,) if user else ())
        return cls(environ.get("NTFY_TOPIC", "").strip(), user, environ.get("GMAIL_APP_PASSWORD", "").strip(), recipients)

    @property
    def has_ntfy(self) -> bool:
        return bool(self.ntfy_topic)

    @property
    def has_email(self) -> bool:
        return bool(self.gmail_user and self.gmail_password and self.recipients)

    def push(self, title: str, message: str) -> str:
        """Returnerar 'sent', 'skipped' eller 'failed'. Kastar aldrig: en notis får inte stoppa agenterna."""
        if not self.has_ntfy:
            return "skipped"
        try:
            send_ntfy(self.ntfy_topic, title, message, self.opener)
            return "sent"
        except Exception as exc:  # noqa: BLE001
            log.error("ntfy misslyckades: %s", type(exc).__name__)
            return "failed"

    def email(self, subject: str, body: str) -> str:
        if not self.has_email:
            return "skipped"
        try:
            send_email(self.gmail_user, self.gmail_password, list(self.recipients), subject, body, self.smtp)
            return "sent"
        except Exception as exc:  # noqa: BLE001
            log.error("e-post misslyckades: %s", type(exc).__name__)
            return "failed"
