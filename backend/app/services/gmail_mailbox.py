import asyncio
import email
import imaplib
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr

from app.core.config import Settings
from app.services.mailpit import MailAttachment, MailMessage, MailSummary, Mailbox, MailpitMailbox


def mailbox_from_settings(settings: Settings) -> Mailbox:
    """Read Gmail when IMAP credentials are set. Otherwise keep the local Mailpit inbox."""
    if settings.imap_username.strip() and settings.imap_password.strip():
        return GmailMailbox(settings)
    return MailpitMailbox(settings)


def parse_gmail_message(raw: bytes, message_id: str) -> tuple[MailMessage, dict[str, bytes]]:
    """Turn one RFC822 message into a subject, sender, and downloadable CV parts."""
    parsed = email.message_from_bytes(raw)
    attachments: list[MailAttachment] = []
    bodies: dict[str, bytes] = {}
    for index, part in enumerate(parsed.walk()):
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        part_id = str(index)
        attachments.append(MailAttachment(part_id=part_id, filename=_decode_header(filename)))
        bodies[part_id] = payload
    return (
        MailMessage(
            message_id=message_id,
            subject=_decode_header(parsed.get("Subject")),
            from_address=parseaddr(_decode_header(parsed.get("From")))[1],
            attachments=attachments,
        ),
        bodies,
    )


class GmailMailbox:
    """Read a Gmail inbox over IMAP without marking messages as read."""

    def __init__(self, settings: Settings) -> None:
        self._host = settings.imap_host
        self._port = settings.imap_port
        self._username = settings.imap_username
        self._password = settings.imap_password

    async def list_summaries(self) -> list[MailSummary]:
        return await asyncio.to_thread(self._list_summaries)

    async def read_message(self, message_id: str) -> MailMessage:
        raw = await asyncio.to_thread(self._fetch_rfc822, message_id)
        message, _bodies = parse_gmail_message(raw, message_id)
        return message

    async def download(self, message_id: str, part_id: str) -> bytes:
        raw = await asyncio.to_thread(self._fetch_rfc822, message_id)
        _message, bodies = parse_gmail_message(raw, message_id)
        body = bodies.get(part_id)
        if body is None:
            raise RuntimeError("Gmail attachment was not found.")
        return body

    def _list_summaries(self) -> list[MailSummary]:
        client = self._connect()
        try:
            client.select("INBOX", readonly=True)
            _status, data = client.uid("SEARCH", None, "ALL")
            raw_ids = data[0].split() if data and data[0] else []
            summaries: list[MailSummary] = []
            for uid in reversed(raw_ids[-50:]):
                message_id = uid.decode() if isinstance(uid, bytes) else str(uid)
                header = self._fetch_header(client, message_id)
                if header is None:
                    continue
                summaries.append(
                    MailSummary(
                        message_id=message_id,
                        subject=_decode_header(header.get("Subject")),
                        from_address=parseaddr(_decode_header(header.get("From")))[1],
                    )
                )
            return summaries
        finally:
            client.logout()

    def _fetch_rfc822(self, message_id: str) -> bytes:
        client = self._connect()
        try:
            client.select("INBOX", readonly=True)
            _status, fetched = client.uid("FETCH", message_id, "(BODY.PEEK[])")
            raw = _first_bytes(fetched)
            if raw is None:
                raise RuntimeError("Gmail did not return the message.")
            return raw
        finally:
            client.logout()

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self._host, self._port)
        client.login(self._username, self._password)
        return client

    def _fetch_header(self, client: imaplib.IMAP4_SSL, message_id: str) -> Message | None:
        _status, fetched = client.uid("FETCH", message_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
        raw = _first_bytes(fetched)
        if raw is None:
            return None
        return email.message_from_bytes(raw)


def _first_bytes(fetched: object) -> bytes | None:
    if not isinstance(fetched, list):
        return None
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    chunks: list[str] = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            chunks.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            chunks.append(text)
    return "".join(chunks)
