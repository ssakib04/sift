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
    )
    SmtpInviteSender(settings).send("ada@example.com", "Interview invitation: Engineer", "Open your link")
    assert sent[0]["To"] == "ada@example.com"
    assert sent[0]["From"] == "jobs@sift.local"
