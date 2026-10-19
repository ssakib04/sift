from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_recruiter
from app.core.database import get_session
from app.schemas.progress import ProgressBoardRead
from app.services.progress import list_progress

router = APIRouter(dependencies=[Depends(require_recruiter)])


@router.get("/progress", response_model=list[ProgressBoardRead])
async def read_progress(session: AsyncSession = Depends(get_session)) -> list[ProgressBoardRead]:
    return await list_progress(session)
