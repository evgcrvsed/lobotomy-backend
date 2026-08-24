from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import ExportJob
from backend.schemas.export import ExportJobResponse
from backend.services.auth_service import get_current_admin
from backend.services.sheets_export import configuration_problem

router = APIRouter(prefix="/api/export", tags=["export"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]

# Задача считается незаконченной, пока воркер её не закрыл
OPEN_STATUSES = ("pending", "running")


async def _last_job(db: AsyncSession) -> ExportJob | None:
    result = await db.execute(select(ExportJob).order_by(ExportJob.id.desc()).limit(1))
    return result.scalar_one_or_none()


@router.post("/sheets", response_model=ExportJobResponse, dependencies=admin_only)
async def start_sheets_export(db: DbDep):
    """Ставит выгрузку в очередь. Сама выгрузка идёт в отдельном контейнере
    (backend/workers/sheets.py) — здесь только появляется строка в export_jobs.

    Настройки проверяем прямо тут, хотя ходить в Google не нам: без них задача
    легла бы в очередь и вечно висела «в работе», а человек у кнопки не понял бы,
    почему ничего не происходит.
    """
    problem = configuration_problem()
    if problem is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Выгрузка не настроена: {problem}",
        )

    # Уже стоит в очереди или выполняется — отдаём её же, а не плодим вторую:
    # два одновременных прохода по одной таблице только жгли бы лимиты Google
    result = await db.execute(
        select(ExportJob)
        .where(ExportJob.status.in_(OPEN_STATUSES))
        .order_by(ExportJob.id)
        .limit(1)
    )
    running = result.scalar_one_or_none()
    if running is not None:
        return running

    job = ExportJob(status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/sheets", response_model=ExportJobResponse | None, dependencies=admin_only)
async def sheets_export_status(db: DbDep):
    """Последняя выгрузка: её и опрашивает админка, пока задача не закроется.
    None — выгрузку ещё ни разу не запускали."""
    return await _last_job(db)
