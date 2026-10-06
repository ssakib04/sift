from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings


class MailSummary(BaseModel):
    message_id: str
    subject: str
    from_address: str


class MailAttachment(BaseModel):
    part_id: str
    filename: str


class MailMessage(BaseModel):
    message_id: str
    subject: str
    from_address: str
    attachments: list[MailAttachment] = Field(default_factory=list)


class Mailbox(Protocol):
    async def list_summaries(self) -> list[MailSummary]:
        """Return inbox messages, newest first."""

    async def read_message(self, message_id: str) -> MailMessage:
        """Return one message and its attachment descriptors."""

    async def download(self, message_id: str, part_id: str) -> bytes:
        """Return one attachment body."""


class MailpitMailbox:
    """Read the local Mailpit inbox over its HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.mailpit_base_url.rstrip("/")

    async def list_summaries(self) -> list[MailSummary]:
        payload = await self._get_json("/api/v1/messages", params={"limit": 50})
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []
        summaries: list[MailSummary] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("ID") or "")
            if not message_id:
                continue
            summaries.append(
                MailSummary(
                    message_id=message_id,
                    subject=str(item.get("Subject") or ""),
                    from_address=_address(item.get("From")),
                )
            )
        return summaries

    async def read_message(self, message_id: str) -> MailMessage:
        payload = await self._get_json(f"/api/v1/message/{message_id}")
        raw_attachments = payload.get("Attachments")
        attachments: list[MailAttachment] = []
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if not isinstance(item, dict):
                    continue
                part_id = str(item.get("PartID") or "")
                filename = str(item.get("FileName") or "")
                if part_id and filename:
                    attachments.append(MailAttachment(part_id=part_id, filename=filename))
        return MailMessage(
            message_id=message_id,
            subject=str(payload.get("Subject") or ""),
            from_address=_address(payload.get("From")),
            attachments=attachments,
        )

    async def download(self, message_id: str, part_id: str) -> bytes:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self._base}/api/v1/message/{message_id}/part/{part_id}")
            response.raise_for_status()
            return response.content

    async def _get_json(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self._base}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Mailpit returned an unexpected payload.")
        return payload


def _address(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("Address") or value.get("address") or "")
    return ""
