from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm
from app.api.v1.auth import require_recruiter
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.claims import ClaimVerificationRead
from app.services.cv_claims import ClaimError, build_claim_verification, read_claim_verification

router = APIRouter(dependencies=[Depends(require_recruiter)])


def _http(exc: ClaimError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error_code": exc.code, "message": exc.message})


@router.get("/candidates/{candidate_id}/claim-verification", response_model=ClaimVerificationRead)
async def read_claims(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> ClaimVerificationRead:
    try:
        return await read_claim_verification(session, candidate_id)
    except ClaimError as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/claim-verification", response_model=ClaimVerificationRead)
async def create_claims(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> ClaimVerificationRead:
    try:
        return await build_claim_verification(session, llm, candidate_id)
    except ClaimError as exc:
        raise _http(exc) from exc
