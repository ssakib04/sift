from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.core.database import get_session
from app.schemas.screening import InviteRead
from app.services.screening import resolve_invite

router = APIRouter(prefix="/invites")


@router.get("/{token}", response_model=InviteRead)
async def read_invite(
    token: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> InviteRead:
    invite = await resolve_invite(session, token, settings)
    if invite is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "INVITE_NOT_FOUND", "message": "This invitation link is not valid."},
        )
    return invite
