import pytest

from app.services.interview_rooms import SignalHub


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_offer_is_relayed_only_to_the_other_person() -> None:
    hub = SignalHub()
    recruiter = FakeSocket()
    candidate = FakeSocket()
    await hub.join("room-1", "recruiter", recruiter)
    await hub.join("room-1", "candidate", candidate)
    await hub.relay("room-1", "recruiter", {"type": "offer", "sdp": {"type": "offer", "sdp": "v=0"}})
    assert candidate.sent[-1]["type"] == "offer"
    assert candidate.sent[-1]["from"] == "recruiter"
    assert all(item.get("type") != "offer" for item in recruiter.sent)
    assert any(item.get("type") == "peer-joined" for item in recruiter.sent)


@pytest.mark.asyncio
async def test_a_rejoined_role_closes_the_previous_socket() -> None:
    hub = SignalHub()
    first = FakeSocket()
    second = FakeSocket()
    await hub.join("room-1", "candidate", first)
    await hub.join("room-1", "candidate", second)
    assert first.closed is True
    assert second.closed is False
