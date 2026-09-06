from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.auth_service import get_current_admin
from backend.services.settings_service import MAX_VALUE_LENGTH, SettingsService, UnknownSettingError

router = APIRouter(prefix="/api/settings", tags=["settings"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]


class SettingUpdate(BaseModel):
    value: str = Field(default="", max_length=MAX_VALUE_LENGTH)


@router.get("/", response_model=dict[str, str])
async def get_settings(db: DbDep, response: Response):
    """Тексты витрины — нужны публично, их показывают обычным посетителям."""
    response.headers["Cache-Control"] = "private, max-age=60"
    return await SettingsService(db).get_all()


@router.put("/{key}", response_model=dict[str, str], dependencies=admin_only)
async def update_setting(key: str, data: SettingUpdate, db: DbDep):
    service = SettingsService(db)
    try:
        await service.set(key, data.value)
    except UnknownSettingError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return await service.get_all()
