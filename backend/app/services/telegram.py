import html

import httpx

from app.services.postajob import PublishRequest, PublishResult

_MESSAGE_LIMIT = 4096


class TelegramError(RuntimeError):
    """Telegram rejected the channel post."""


def build_channel_text(request: PublishRequest) -> str:
    description = request.description.strip()
    header = (
        f"<b>{_escape(request.title)}</b>\n"
        f"{_escape(request.company_name)} · {_escape(request.seniority)} · {_escape(request.contract)}\n\n"
    )
    apply_note = ""
    if request.apply_email.strip() and request.mail_subject.strip():
        apply_note = (
            f"\n\nEmail a PDF or DOCX CV to {_escape(request.apply_email)}."
            f"\nSubject: {_escape(request.mail_subject)}"
        )
    footer = f'{apply_note}\n\n<a href="{_escape(request.apply_url)}">Apply</a>'
    room = _MESSAGE_LIMIT - len(header) - len(footer)
    if len(description) > room:
        description = description[: max(room - 1, 0)].rstrip() + "…"
    return f"{header}{_escape(description)}{footer}"


def channel_message_url(chat_id: str, message_id: int) -> str | None:
    if chat_id.startswith("@") and len(chat_id) > 1:
        return f"https://t.me/{chat_id[1:]}/{message_id}"
    return None


class TelegramPoster:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client

    async def publish(self, request: PublishRequest) -> PublishResult:
        payload = {
            "chat_id": self._chat_id,
            "text": build_channel_text(request),
            "parse_mode": "HTML",
        }
        if self._client is None:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._send(client, payload)
        return await self._send(self._client, payload)

    async def _send(self, client: httpx.AsyncClient, payload: dict[str, str]) -> PublishResult:
        response = await client.post(f"https://api.telegram.org/bot{self._bot_token}/sendMessage", json=payload)
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramError(f"telegram_invalid_response:{response.status_code}") from exc
        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("ok"):
            description = body.get("description") if isinstance(body, dict) else None
            reason = description if isinstance(description, str) and description else f"telegram_failed:{response.status_code}"
            raise TelegramError(reason[:128])
        result = body.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int):
            raise TelegramError("telegram_missing_message_id")
        return PublishResult(
            external_id=str(message_id),
            status="live",
            detail=channel_message_url(self._chat_id, message_id),
        )


def _escape(value: str) -> str:
    return html.escape(value, quote=True)
