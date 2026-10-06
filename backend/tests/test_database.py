import pytest

from app.core import database


class _Session:
    def __init__(self) -> None:
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True


class _Context:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.closed = False

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.closed = True
        return False


@pytest.mark.asyncio
async def test_get_session_yields_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    context = _Context(session)
    monkeypatch.setattr(database, "SessionFactory", lambda: context)

    generator = database.get_session()
    yielded = await anext(generator)
    assert yielded is session
    await generator.aclose()

    assert context.closed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_get_session_rolls_back_when_the_request_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    context = _Context(session)
    monkeypatch.setattr(database, "SessionFactory", lambda: context)

    generator = database.get_session()
    await anext(generator)
    with pytest.raises(RuntimeError, match="request failed"):
        await generator.athrow(RuntimeError("request failed"))

    assert session.rolled_back is True
    assert context.closed is True
