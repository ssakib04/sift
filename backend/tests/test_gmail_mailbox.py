from email.message import EmailMessage

from app.core.config import Settings
from app.services.gmail_mailbox import mailbox_from_settings, parse_gmail_message
from app.services.mailpit import MailpitMailbox


def _cv_message() -> bytes:
    message = EmailMessage()
    message["Subject"] = "Application: Front End Developer"
    message["From"] = "Ada Lovelace <ada@example.com>"
    message.set_content("CV attached.")
    message.add_attachment(b"%PDF-1.4 sample", maintype="application", subtype="pdf", filename="ada.pdf")
    return message.as_bytes()


def test_parse_gmail_message_keeps_subject_sender_and_pdf() -> None:
    parsed, bodies = parse_gmail_message(_cv_message(), "41")
    assert parsed.message_id == "41"
    assert parsed.subject == "Application: Front End Developer"
    assert parsed.from_address == "ada@example.com"
    assert len(parsed.attachments) == 1
    attachment = parsed.attachments[0]
    assert attachment.filename == "ada.pdf"
    assert bodies[attachment.part_id].startswith(b"%PDF")


def test_mailbox_uses_gmail_only_when_credentials_exist() -> None:
    empty = Settings(_env_file=None, imap_username="", imap_password="")
    ready = Settings(_env_file=None, imap_username="kazisadmansakib@gmail.com", imap_password="app-password")
    assert isinstance(mailbox_from_settings(empty), MailpitMailbox)
    assert type(mailbox_from_settings(ready)).__name__ == "GmailMailbox"