"""Process-wide logs with a request id, and one line for each HTTP call."""

import json
import logging
import re
import sys
import time
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings, get_settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("app.request")

_HANDLER_NAME = "sift"
_FILE_HANDLER_NAME = "sift-file"
_LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_AUTHORIZATION = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|id_token|token|password|secret|api_key|apikey)=)[^&\s\"']+"
)
_FACTORY_FLAG = "_sift_request_id"


def new_request_id() -> str:
    return f"req_{uuid4().hex[:12]}"


def redact_secrets(text: str) -> str:
    """Hide bearer tokens, Authorization values, and secret query parameters."""
    text = _BEARER.sub("Bearer [redacted]", text)
    text = _AUTHORIZATION.sub(r"\1[redacted]", text)
    return _QUERY_SECRET.sub(r"\1[redacted]", text)


class RedactingFormatter(logging.Formatter):
    """Render a log record and strip credentials from the finished line."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return redact_secrets(super().format(record))


def error_payload(request_id: str) -> dict[str, Any]:
    return {
        "detail": {
            "error_code": "INTERNAL_ERROR",
            "message": "Something went wrong.",
            "request_id": request_id,
        }
    }


def configure_logging(settings: Settings | None = None) -> None:
    """Send every process's logs to stdout, and to a rotating file when log_dir is set."""
    active = settings or get_settings()
    _install_record_factory()
    root = logging.getLogger()
    root.setLevel(_LOG_LEVELS[active.log_level])
    logging.captureWarnings(True)
    for name in ("uvicorn.access", "httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if any(getattr(handler, "name", "") == _HANDLER_NAME for handler in root.handlers):
        return
    formatter = _formatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.name = _HANDLER_NAME
    stream.setFormatter(formatter)
    root.addHandler(stream)
    if active.log_dir:
        file_handler = _file_handler(Path(active.log_dir))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def register_exception_logging(app: FastAPI) -> None:
    """Turn an unhandled error into a JSON body that carries the request id."""

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        request_id = request_id_var.get()
        logger.exception(
            "unhandled_exception method=%s path=%s error_type=%s",
            _safe_method(request.method),
            _safe_path(request.url.path),
            type(exc).__name__,
        )
        return JSONResponse(status_code=500, content=error_payload(request_id))


class RequestLogMiddleware:
    """Log method, path, status, and duration. Leave headers, query strings, and bodies out."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await self._http(scope, receive, send)

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = new_request_id()
        token = request_id_var.set(request_id)
        method = _safe_method(str(scope.get("method", "GET")))
        path = _safe_path(str(scope.get("path", "/")))
        started = time.perf_counter()
        status_code = 0
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            logger.exception(
                "unhandled_exception method=%s path=%s error_type=%s",
                method,
                path,
                type(exc).__name__,
            )
            if response_started:
                raise
            status_code = 500
            await _send_error(send, request_id)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            _log_http(method, path, status_code, duration_ms)
            request_id_var.reset(token)

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = request_id_var.set(new_request_id())
        path = _safe_path(str(scope.get("path", "/")))
        logger.info("websocket_connected path=%s", path)
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            logger.exception("websocket_failed path=%s error_type=%s", path, type(exc).__name__)
            raise
        finally:
            logger.info("websocket_closed path=%s", path)
            request_id_var.reset(token)


def _install_record_factory() -> None:
    current = logging.getLogRecordFactory()
    if getattr(current, _FACTORY_FLAG, False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record

    setattr(factory, _FACTORY_FLAG, True)
    logging.setLogRecordFactory(factory)


def _formatter() -> RedactingFormatter:
    return RedactingFormatter(
        "%(asctime)s level=%(levelname)s logger=%(name)s request_id=%(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _file_handler(directory: Path) -> RotatingFileHandler:
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "sift.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.name = _FILE_HANDLER_NAME
    return handler


def _log_http(method: str, path: str, status_code: int, duration_ms: int) -> None:
    if status_code < 400 and _quiet_path(path):
        return
    if status_code >= 500:
        level = logging.ERROR
        event = "request_failed"
    elif status_code >= 400:
        level = logging.WARNING
        event = "request_rejected"
    elif status_code == 0:
        level = logging.WARNING
        event = "request_closed"
    else:
        level = logging.INFO
        event = "request_completed"
    logger.log(
        level,
        "%s method=%s path=%s status=%s duration_ms=%s",
        event,
        method,
        path,
        status_code,
        duration_ms,
    )


def _quiet_path(path: str) -> bool:
    return path.rstrip("/").endswith("/health")


def _safe_method(method: str) -> str:
    cleaned = "".join(character for character in method if character.isascii() and character.isalnum())
    return cleaned[:16] or "GET"


def _safe_path(path: str) -> str:
    cleaned = path.split("?", 1)[0].replace("\r", "").replace("\n", "")
    return cleaned[:512] or "/"


async def _send_error(send: Send, request_id: str) -> None:
    body = json.dumps(error_payload(request_id)).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-request-id", request_id.encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
