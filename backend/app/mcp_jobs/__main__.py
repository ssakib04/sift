from app.core.config import get_settings
from app.core.logging import configure_logging
from app.mcp_jobs.server import build_job_server
from app.services.telegram import TelegramPoster


def main() -> None:
    configure_logging()
    settings = get_settings()
    poster = TelegramPoster(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    server = build_job_server(poster)
    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8080,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
