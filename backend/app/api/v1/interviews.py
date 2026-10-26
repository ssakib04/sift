from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.core.database import get_session
from app.schemas.interviews import RoleInterviewsRead
from app.services.interview_agenda import list_scheduled_interviews

router = APIRouter()


@router.get("/interviews", response_model=list[RoleInterviewsRead])
async def read_interviews(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> list[RoleInterviewsRead]:
    return await list_scheduled_interviews(session, zone_name=settings.interview_timezone)
