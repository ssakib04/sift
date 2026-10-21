from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_recruiter
from app.core.database import get_session
from app.schemas.notice import ApplicantNoticeListRead, ApplicantNoticeRead
from app.services.notices import list_notices, mark_notice_read

router = APIRouter(dependencies=[Depends(require_recruiter)])


@router.get("/notifications", response_model=ApplicantNoticeListRead)
async def read_notifications(session: AsyncSession = Depends(get_session)) -> ApplicantNoticeListRead:
    return await list_notices(session)


@router.post("/notifications/{notice_id}/read", response_model=ApplicantNoticeRead)
async def read_notification(
    notice_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ApplicantNoticeRead:
    notice = await mark_notice_read(session, notice_id)
    if notice is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOTICE_NOT_FOUND", "message": "That applicant notice is no longer here."},
        )
    return notice
