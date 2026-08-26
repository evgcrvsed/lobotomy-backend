from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import ExportJob
from backend.schemas.export import ExportJobResponse, SheetsExportStatus
from backend.services.auth_service import get_current_admin
from backend.services.sheets_export import configuration_problem, spreadsheet_url

router = APIRouter(prefix="/api/export", tags=["export"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]

# Задача считается незаконченной, пока воркер её не закрыл
OPEN_STATUSES = ("pending", "running")


async def _expire_abandoned(db: AsyncSession) -> None:
    """Закрывает задачи, которые никто не доведёт до конца.

    Воркер может не дойти до очереди вовсе (контейнер лежит) — тогда задача
    навсегда остаётся pending, а кнопка в админке бесконечно показывает
    «синхронизируем». Так и случилось на проде 26.08.2026. Сам воркер о таких
    задачах ничего сказать не может — его нет, — поэтому подводит черту тот,
    к кому админка приходит за статусом.

    Окно с запасом: свой потолок у воркера меньше, так что в норме он успевает
    закрыть задачу сам, и мы забираем только по-настоящему брошенные.
    """
    window = settings.sheets_job_timeout_minutes + settings.sheets_job_abandon_slack_minutes
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window)
    result = await db.execute(
        update(ExportJob)
        .where(ExportJob.status.in_(OPEN_STATUSES), ExportJob.created_at < cutoff)
        .values(
            status="error",
            message=(
                f"Выгрузка не завершилась за {window} мин. "
                f"Чёто пиздец, надо контейнер sheets-worker чекать."
            ),
            finished_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount:
        await db.commit()


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

    await _expire_abandoned(db)

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


@router.get("/sheets", response_model=SheetsExportStatus, dependencies=admin_only)
async def sheets_export_status(db: DbDep):
    """Что показывать в админке: последняя задача и адрес самой таблицы.
    Этот же эндпоинт админка опрашивает, пока задача не закроется."""
    await _expire_abandoned(db)
    return SheetsExportStatus(sheet_url=spreadsheet_url(), job=await _last_job(db))
