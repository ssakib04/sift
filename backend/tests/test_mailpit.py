import httpx
import pytest

from app.core.config import Settings
from app.services.mailpit import MailpitMailbox


@pytest.mark.asyncio
async def test_mailpit_lists_subject_and_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "messages": [
                    {
                        "ID": "msg-1",
                        "Subject": "Senior Python Engineer",
                        "From": {"Address": "ada@example.com"},
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def get(self, url: str, params: dict[str, object] | None = None) -> FakeResponse:
            assert url.endswith("/api/v1/messages")
            assert params == {"limit": 50}
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    summaries = await MailpitMailbox(Settings(_env_file=None)).list_summaries()
    assert summaries[0].message_id == "msg-1"
    assert summaries[0].from_address == "ada@example.com"
    assert summaries[0].subject == "Senior Python Engineer"
