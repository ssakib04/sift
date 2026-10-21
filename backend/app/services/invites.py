import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


class InviteSender(Protocol):
    def send(self, to_address: str, subject: str, body: str, *, attachment_ics: str = "") -> None:
        """Deliver one invitation email, with a calendar file when one is ready."""


class SmtpInviteSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, to_address: str, subject: str, body: str, *, attachment_ics: str = "") -> None:
        message = EmailMessage()
        message["From"] = self._settings.invite_from_address
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)
        if attachment_ics.strip():
            message.add_attachment(
                attachment_ics.encode("utf-8"),
                maintype="text",
                subtype="calendar",
                filename="interview.ics",
            )
            for part in message.iter_attachments():
                if part.get_content_subtype() == "calendar":
                    part.set_param("method", "REQUEST")
        username, password = _smtp_credentials(self._settings)
        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=20) as client:
            if username and password:
                client.ehlo()
                client.starttls()
                client.ehlo()
                client.login(username, password)
            client.send_message(message)


def _smtp_credentials(settings: Settings) -> tuple[str, str]:
    """Use SMTP login when set, otherwise the same mailbox that receives CVs."""
    username = settings.smtp_username.strip() or settings.imap_username.strip()
    password = settings.smtp_password.strip() or settings.imap_password.strip()
    return username, password


def invitation_body(
    *,
    candidate_name: str,
    job_title: str,
    company_name: str,
    url: str,
    when_label: str,
    calendar_line: str,
) -> str:
    who = candidate_name.strip()
    opening = f"Congratulations, {who}." if who else "Congratulations."
    return (
        f"{opening}\n\n"
        f"You have been selected to interview for {job_title} at {company_name}. "
        f"We are glad you applied, and we would like to meet you.\n\n"
        f"Your interview is scheduled for {when_label}.\n"
        f"{calendar_line}\n\n"
        f"When it is time, open your interview here:\n{url}\n\n"
        "We look forward to speaking with you.\n"
    )
