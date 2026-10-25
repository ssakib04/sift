from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm
from app.api.v1.auth import require_recruiter
from app.core.database import get_session
from app.core.llm_fallback import FallbackLLMManager
from app.schemas.interview import AnalysisRead, AnalysisRunRead, JustificationRead, QAPairRead, ReportRetryRead
from app.schemas.interview_quality import InterviewQualityRead
from app.schemas.interview_score import InterviewHistoryRead, InterviewScoreRead
from app.services.interview_quality import QualityError, build_interview_quality, read_interview_quality
from app.services.interview_rules import InterviewError
from app.services.interview_sessions import request_interview_analysis, retry_report
from app.services.interview_score import (
    ScoreError,
    build_interview_score,
    list_interview_history,
    read_candidate_analysis,
    read_interview_score,
)

router = APIRouter(dependencies=[Depends(require_recruiter)])


def _http(exc: ScoreError | QualityError | InterviewError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error_code": exc.code, "message": exc.message})


@router.get("/interview-history", response_model=list[InterviewHistoryRead])
async def read_history(session: AsyncSession = Depends(get_session)) -> list[InterviewHistoryRead]:
    return await list_interview_history(session)


@router.get("/candidates/{candidate_id}/interview-score", response_model=InterviewScoreRead)
async def read_score(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> InterviewScoreRead:
    try:
        return await read_interview_score(session, candidate_id)
    except ScoreError as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/interview-score", response_model=InterviewScoreRead)
async def create_score(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> InterviewScoreRead:
    try:
        return await build_interview_score(session, llm, candidate_id)
    except ScoreError as exc:
        raise _http(exc) from exc


@router.get("/candidates/{candidate_id}/interview-quality", response_model=InterviewQualityRead)
async def read_quality(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> InterviewQualityRead:
    try:
        return await read_interview_quality(session, candidate_id)
    except QualityError as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/interview-quality", response_model=InterviewQualityRead)
async def create_quality(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> InterviewQualityRead:
    try:
        return await build_interview_quality(session, candidate_id)
    except QualityError as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/reports/retry", response_model=ReportRetryRead)
async def retry_reports(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> ReportRetryRead:
    try:
        restarted = await retry_report(session, llm, candidate_id)
    except InterviewError as exc:
        raise _http(exc) from exc
    return ReportRetryRead(restarted=restarted)


@router.post("/candidates/{candidate_id}/interview-analysis", response_model=AnalysisRunRead)
async def create_analysis(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    llm: FallbackLLMManager = Depends(get_llm),
) -> AnalysisRunRead:
    try:
        state = await request_interview_analysis(session, llm, candidate_id)
    except InterviewError as exc:
        raise _http(exc) from exc
    return AnalysisRunRead(state=state)


@router.get("/candidates/{candidate_id}/interview-analysis", response_model=AnalysisRead)
async def read_analysis(candidate_id: UUID, session: AsyncSession = Depends(get_session)) -> AnalysisRead:
    try:
        analysis = await read_candidate_analysis(session, candidate_id)
    except ScoreError as exc:
        raise _http(exc) from exc
    return AnalysisRead(
        relevance=analysis.relevance,
        technical_accuracy=analysis.technical_accuracy,
        completeness=analysis.completeness,
        articulation=analysis.articulation,
        gaps=list(analysis.gaps or []),
        discrepancies=list(analysis.discrepancies or []),
        summary=analysis.summary,
        justifications=[
            JustificationRead(claim=str(item.get("claim") or ""), citation=str(item.get("citation") or ""))
            for item in analysis.justifications or []
            if isinstance(item, dict)
        ],
        pairs=[
            QAPairRead(
                pair_id=pair.pair_id,
                question=pair.question,
                answer=pair.answer,
                intent=pair.intent,
                citation=pair.citation,
                query_ids=list(pair.query_ids or []),
                relevance=pair.relevance,
                technical_accuracy=pair.technical_accuracy,
                completeness=pair.completeness,
                articulation=pair.articulation,
            )
            for pair in sorted(analysis.pairs, key=lambda item: item.sequence)
        ],
        llm_tier=analysis.llm_tier,
        fallback_used=analysis.fallback_used,
    )
