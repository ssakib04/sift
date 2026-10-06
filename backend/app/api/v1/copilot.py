from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_embedder, get_llm
from app.core.config import Settings
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.job_creation_graph import JobGraphError
from app.schemas.copilot import CopilotTurnRequest, CopilotTurnResponse
from app.services.copilot import run_copilot_turn
from app.services.embeddings import Embedder
from app.services.policy_ingest import PgPolicyRetriever

router = APIRouter(prefix="/copilot")


@router.post("/messages", response_model=CopilotTurnResponse)
async def copilot_message(
    request: CopilotTurnRequest,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_app_settings),
) -> CopilotTurnResponse:
    try:
        return await run_copilot_turn(
            session,
            request.messages,
            llm=llm,
            retriever=PgPolicyRetriever(session, embedder),
            settings=settings,
        )
    except JobGraphError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "JOB_GENERATION_INVALID", "message": str(exc)},
        ) from exc
    except LLMFallbackExhaustedError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "LLM_UNAVAILABLE", "message": "Every LLM tier failed."},
        ) from exc
