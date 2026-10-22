import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_embedder, get_llm
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.policy import PolicyDocumentRead, PolicySummaryRead
from app.services.documents import EmptyDocumentError, UnsupportedDocumentError
from app.services.embeddings import Embedder
from app.services.policy_ingest import get_policy, ingest_policy, list_policies, summarize_policy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policies")
_MAX_BYTES = 10 * 1024 * 1024


@router.get("", response_model=list[PolicyDocumentRead])
async def read_policies(session: AsyncSession = Depends(get_session)) -> list[PolicyDocumentRead]:
    documents = await list_policies(session)
    return [
        PolicyDocumentRead(
            id=document.id,
            filename=document.filename,
            media_type=document.media_type,
            created_at=document.created_at,
            chunk_count=len(document.chunks),
        )
        for document in documents
    ]


@router.get("/{document_id}/summary", response_model=PolicySummaryRead)
async def read_policy_summary(
    document_id: UUID,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> PolicySummaryRead:
    document = await get_policy(session, document_id)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "POLICY_NOT_FOUND", "message": "Policy not found."},
        )
    ordered = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)
    text = "\n".join(chunk.text for chunk in ordered)
    try:
        summary = await summarize_policy(llm, document.filename, text)
    except Exception as exc:
        logger.warning("policy_summary_failed error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail={"error_code": "POLICY_SUMMARY_UNAVAILABLE", "message": "The local model could not summarize this policy."},
        ) from exc
    return PolicySummaryRead(id=document.id, summary=summary)


@router.post("", response_model=PolicyDocumentRead, status_code=201)
async def upload_policy(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_app_settings),
) -> PolicyDocumentRead:
    filename = file.filename or "policy"
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error_code": "POLICY_TOO_LARGE", "message": "Policy files must be 10 MB or smaller."},
        )
    try:
        document = await ingest_policy(
            session,
            filename=filename,
            media_type=file.content_type or "application/octet-stream",
            data=data,
            embedder=embedder,
            storage_dir=Path(settings.policy_storage_dir),
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=415,
            detail={"error_code": "POLICY_TYPE_UNSUPPORTED", "message": str(exc)},
        ) from exc
    except EmptyDocumentError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "POLICY_EMPTY", "message": str(exc)},
        ) from exc
    return PolicyDocumentRead(
        id=document.id,
        filename=document.filename,
        media_type=document.media_type,
        created_at=document.created_at,
        chunk_count=len(document.chunks),
    )
