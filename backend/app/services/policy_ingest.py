import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm_fallback import LLMResponse
from app.models.policy import PolicyChunk, PolicyDocument
from app.services.documents import chunk_text, extract_text
from app.services.embeddings import Embedder

_SUMMARY_CHARS = 3600
_SUMMARY_OUTPUT = 480


async def ingest_policy(
    session: AsyncSession,
    *,
    filename: str,
    media_type: str,
    data: bytes,
    embedder: Embedder,
    storage_dir: Path,
) -> PolicyDocument:
    text = extract_text(filename, data)
    chunks = chunk_text(text)
    vectors = await asyncio.to_thread(embedder.embed, chunks)
    storage_dir.mkdir(parents=True, exist_ok=True)
    document_id = uuid.uuid4()
    destination = storage_dir / f"{document_id}{Path(filename).suffix.lower()}"
    destination.write_bytes(data)
    document = PolicyDocument(
        id=document_id,
        filename=Path(filename).name,
        media_type=media_type,
        storage_path=str(destination),
        created_at=datetime.now(UTC),
    )
    document.chunks = [
        PolicyChunk(document_id=document_id, chunk_index=index, text=chunk, embedding=vector)
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    ]
    session.add(document)
    await session.commit()
    return document


class LocalModel(Protocol):
    async def complete_local(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        """Ask the on-box model only."""


async def get_policy(session: AsyncSession, document_id: UUID) -> PolicyDocument | None:
    statement = (
        select(PolicyDocument)
        .options(selectinload(PolicyDocument.chunks))
        .where(PolicyDocument.id == document_id)
    )
    return (await session.scalars(statement)).unique().one_or_none()


async def summarize_policy(llm: LocalModel, filename: str, text: str) -> str:
    """Two short sentences from the local model, using only the stored policy text."""
    excerpt = " ".join(text.split())
    if not excerpt:
        return "This document has no readable text."
    result = await llm.complete_local(
        f"Filename: {filename}\n\n{excerpt[:_SUMMARY_CHARS]}",
        system=(
            "Summarize this company policy for a recruiter in two short sentences. "
            "Say what the document covers. Do not invent rules that are not in the text. "
            "Reply with the two sentences only."
        ),
    )
    return _tidy_summary(result.content)


def _tidy_summary(content: str) -> str:
    summary = " ".join(content.split())
    if summary.lower().startswith("here is"):
        colon = summary.find(":")
        if 0 < colon < 140:
            summary = summary[colon + 1 :].strip()
    if len(summary) > _SUMMARY_OUTPUT:
        summary = summary[:_SUMMARY_OUTPUT].rsplit(" ", 1)[0].rstrip(" ,;:")
    summary = summary.strip()
    return summary or "No summary was returned."


async def list_policies(session: AsyncSession) -> list[PolicyDocument]:
    statement = select(PolicyDocument).options(selectinload(PolicyDocument.chunks)).order_by(
        PolicyDocument.created_at.desc()
    )
    return list((await session.scalars(statement)).unique().all())


class PgPolicyRetriever:
    def __init__(self, session: AsyncSession, embedder: Embedder) -> None:
        self._session = session
        self._embedder = embedder

    async def search(self, query: str, limit: int = 5) -> list[str]:
        vector = (await asyncio.to_thread(self._embedder.embed, [query]))[0]
        distance = PolicyChunk.embedding.cosine_distance(vector)
        statement = select(PolicyChunk.text).order_by(distance).limit(limit)
        return list((await self._session.scalars(statement)).all())
