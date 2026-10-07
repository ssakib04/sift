import json

from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import Implementation

from app.services.postajob import PublishRequest, PublishResult

_TOOL_NAME = "post_job"


class McpPublishError(RuntimeError):
    """The job MCP server rejected or could not complete a tool call."""


async def publish_via_mcp(server_url: str, request: PublishRequest) -> PublishResult:
    """Call the remote post_job tool over MCP and return its Telegram result."""
    try:
        async with Client(
            server_url,
            client_info=Implementation(name="sift-api", version="1"),
            read_timeout_seconds=30,
        ) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            if _TOOL_NAME not in names:
                raise McpPublishError("The MCP server does not expose post_job")
            result = await client.call_tool(_TOOL_NAME, request.model_dump())
    except MCPError as exc:
        raise McpPublishError(str(exc)) from exc
    if result.is_error:
        raise McpPublishError(_result_text(result) or "post_job failed")
    try:
        payload = json.loads(_result_text(result))
    except json.JSONDecodeError as exc:
        raise McpPublishError("post_job returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise McpPublishError("post_job returned invalid JSON")
    return PublishResult.model_validate(payload)


def _result_text(result: object) -> str:
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)
