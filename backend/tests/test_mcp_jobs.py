import asyncio
import json
import socket
import uuid

import httpx
import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

from app.core.config import Settings
from app.mcp_jobs.server import build_job_server
from app.services.job_service import _publish
from app.services.mcp_publish import McpPublishError, publish_via_mcp
from app.services.postajob import PublishRequest, PublishResult
from app.services.telegram import TelegramPoster


def _request() -> PublishRequest:
    return PublishRequest(
        title="Front End Engineer",
        description="We are hiring a Front End Engineer who can ship React interfaces and work with APIs. " * 2,
        apply_url="http://localhost:3000/careers/version-1",
        contract="Full Time",
        category="Information Technology",
        company_name="Sift",
        company_country="Bangladesh",
        seniority="Mid-Level",
        skills=["React", "Node"],
        version_id="version-1",
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _Version:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.description = "x" * 120
        self.contract = "Full Time"
        self.category = "Information Technology"
        self.seniority = "Mid-Level"
        self.required_skills = ["React"]
        self.preferred_skills = ["Node"]


class _Poster:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, request: PublishRequest) -> PublishResult:
        del request
        self.calls += 1
        return PublishResult(external_id="direct", status="live")


async def _running(server: MCPServer, port: int) -> tuple[uvicorn.Server, asyncio.Task[None]]:
    app = server.streamable_http_app(stateless_http=True, json_response=True, host="127.0.0.1")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    running = uvicorn.Server(config)
    task = asyncio.create_task(running.serve())
    for _ in range(50):
        if running.started:
            return running, task
        await asyncio.sleep(0.05)
    raise RuntimeError("MCP server did not start")


async def _stop(running: uvicorn.Server, task: asyncio.Task[None]) -> None:
    running.should_exit = True
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


@pytest.mark.asyncio
async def test_post_job_tool_sends_telegram_over_mcp() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    port = _free_port()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        poster = TelegramPoster(bot_token="test-token", chat_id="@siftjobs", client=http_client)
        running, task = await _running(build_job_server(poster), port)
        try:
            result = await publish_via_mcp(f"http://127.0.0.1:{port}/mcp", _request())
        finally:
            await _stop(running, task)

    assert result.external_id == "42"
    assert result.status == "live"
    assert result.detail == "https://t.me/siftjobs/42"
    assert len(seen) == 1
    assert seen[0].url.path == "/bottest-token/sendMessage"
    body = json.loads(seen[0].content)
    assert "Front End Engineer" in body["text"]
    assert "http://localhost:3000/careers/version-1" in body["text"]


@pytest.mark.asyncio
async def test_mcp_tool_error_is_reported() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    port = _free_port()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        poster = TelegramPoster(bot_token="test-token", chat_id="@siftjobs", client=http_client)
        running, task = await _running(build_job_server(poster), port)
        try:
            with pytest.raises(McpPublishError):
                await publish_via_mcp(f"http://127.0.0.1:{port}/mcp", _request())
        finally:
            await _stop(running, task)


@pytest.mark.asyncio
async def test_approve_publish_calls_mcp_before_direct_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_publish(url: str, request: PublishRequest) -> PublishResult:
        assert url == "http://mcp:8080/mcp"
        assert request.title == "Front End Engineer"
        return PublishResult(external_id="42", status="live", detail="https://t.me/siftjobs/42")

    monkeypatch.setattr("app.services.job_service.publish_via_mcp", fake_publish)
    poster = _Poster()
    settings = Settings(
        _env_file=None,
        mcp_server_url="http://mcp:8080/mcp",
        telegram_bot_token="test-token",
        telegram_chat_id="@siftjobs",
    )

    posting = await _publish(_Version(), "Front End Engineer", "http://localhost:3000/careers/1", poster, settings)

    assert poster.calls == 0
    assert posting.provider == "mcp"
    assert posting.external_id == "42"
    assert posting.status == "live"
    assert posting.detail == "https://t.me/siftjobs/42"
