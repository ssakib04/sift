from email.message import EmailMessage

from app.core.config import Settings
from app.services.invites import SmtpInviteSender, invitation_body


def test_invitation_body_contains_the_link_only() -> None:
    body = invitation_body(
        job_title="Senior Python Engineer",
        company_name="Sift",
        url="http://localhost:3000/invite/abc",
    )
    assert "http://localhost:3000/invite/abc" in body
    assert "score" not in body.casefold()
    assert "rank" not in body.casefold()


def test_smtp_sender_delivers_to_the_applicant(monkeypatch) -> None:
    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert host == "localhost"
            assert port == 1025

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def send_message(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr("app.services.invites.smtplib.SMTP", FakeSMTP)
    settings = Settings(
        _env_file=None,
        smtp_host="localhost",
        smtp_port=1025,
        invite_from_address="jobs@sift.local",
        imap_username="",
        imap_password="",
    )
    SmtpInviteSender(settings).send("ada@example.com", "Interview invitation: Engineer", "Open your link")
    assert sent[0]["To"] == "ada@example.com"
    assert sent[0]["From"] == "jobs@sift.local"


def test_smtp_sender_logs_in_with_the_mailbox_password(monkeypatch) -> None:
    calls: list[str] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert host == "smtp.gmail.com"
            assert port == 587

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def ehlo(self) -> None:
            calls.append("ehlo")

        def starttls(self) -> None:
            calls.append("starttls")

        def login(self, username: str, password: str) -> None:
            assert username == "fizoadverts@gmail.com"
            assert password == "abcdefghijklmnop"
            calls.append("login")

        def send_message(self, message: EmailMessage) -> None:
            calls.append("send")

    monkeypatch.setattr("app.services.invites.smtplib.SMTP", FakeSMTP)
    settings = Settings(
        _env_file=None,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        invite_from_address="fizoadverts@gmail.com",
        imap_username="fizoadverts@gmail.com",
        imap_password="abcd efgh ijkl mnop",
    )
    SmtpInviteSender(settings).send("ada@example.com", "Interview invitation: Engineer", "Open your link")
    assert calls == ["ehlo", "starttls", "ehlo", "login", "send"]
