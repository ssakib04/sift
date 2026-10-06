import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


class InviteSender(Protocol):
    def send(self, to_address: str, subject: str, body: str) -> None:
        """Deliver one invitation email."""


class SmtpInviteSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to_address: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._settings.invite_from_address
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=15) as client:
            client.send_message(message)


def invitation_body(*, job_title: str, company_name: str, url: str) -> str:
    return (
        f"You are invited to interview for {job_title} at {company_name}.\n\n"
        f"Open your interview link:\n{url}\n"
    )
