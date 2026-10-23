import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.llm_fallback import create_fallback_manager
from app.services.email_worker import ingest_inbox
from app.services.embeddings import create_embedder
from app.services.gmail_mailbox import mailbox_from_settings

logger = logging.getLogger(__name__)


async def poll_forever() -> None:
    settings = get_settings()
    llm = create_fallback_manager()
    embedder = create_embedder()
    mailbox = mailbox_from_settings(settings)
    while True:
        try:
            async with SessionFactory() as session:
                processed = await ingest_inbox(
                    session,
                    settings,
                    llm=llm,
                    embedder=embedder,
                    mailbox=mailbox,
                )
            if processed:
                logger.info("inbox_processed count=%s", processed)
        except Exception:
            logger.exception("inbox_poll_failed")
        await asyncio.sleep(settings.mail_poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(poll_forever())


if __name__ == "__main__":
    main()
