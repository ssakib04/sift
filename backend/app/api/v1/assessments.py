from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm
from app.api.v1.auth import require_recruiter
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.assessment import AssessmentRead, JobComparisonRead
from app.services.assessment import (
    AssessmentError,
    build_consolidated_assessment,
    get_assessment,
    list_comparisons,
    render_assessment_report,
)

router = APIRouter(dependencies=[Depends(require_recruiter)])


def _http(exc: AssessmentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error_code": exc.code, "message": exc.message})


@router.get("/assessments", response_model=list[JobComparisonRead])
async def read_comparisons(session: AsyncSession = Depends(get_session)) -> list[JobComparisonRead]:
    return await list_comparisons(session)


@router.post("/candidates/{candidate_id}/assessment", response_model=AssessmentRead)
async def create_assessment(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> AssessmentRead:
    try:
        return await build_consolidated_assessment(session, llm, candidate_id)
    except AssessmentError as exc:
        raise _http(exc) from exc


@router.get("/candidates/{candidate_id}/assessment", response_model=AssessmentRead)
async def read_assessment(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> AssessmentRead:
    try:
        return await get_assessment(session, candidate_id)
    except AssessmentError as exc:
        raise _http(exc) from exc


@router.get("/candidates/{candidate_id}/assessment/report", response_class=HTMLResponse)
async def download_assessment(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    try:
        report = await get_assessment(session, candidate_id)
    except AssessmentError as exc:
        raise _http(exc) from exc
    html = render_assessment_report(report)
    filename = f"assessment-{candidate_id}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
