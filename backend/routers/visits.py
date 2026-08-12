from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.visit import TrafficStats
from backend.services.auth_service import client_ip, get_current_admin
from backend.services.stats_service import StatsError, resolve_period
from backend.services.visit_service import VisitService, own_hosts

router = APIRouter(prefix="/api/visits", tags=["visits"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]


class VisitIn(BaseModel):
    """Что прислал браузер. referrer — это его document.referrer, каким он есть.

    Заголовку Referer самого запроса верить нельзя: страница уже открыта, и там
    лежит адрес нашего же сайта, а не площадки, откуда пришёл посетитель.
    """

    referrer: str | None = Field(default=None, max_length=2000)


@router.post("/", status_code=status.HTTP_204_NO_CONTENT)
async def record_visit(data: VisitIn, request: Request, db: DbDep):
    """Отметка о заходе. Открыт всем: его зовёт страница магазина при первом открытии.

    Ответ пустой и без подробностей — со стороны браузера считать по нему
    нечего, а фронт его и не читает.
    """
    await VisitService(db).record(data.referrer, own_hosts(request), client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=TrafficStats, dependencies=admin_only)
async def traffic_stats(db: DbDep, date_from: date | None = None, date_to: date | None = None):
    """Откуда пришли за период — для круговой диаграммы в админке."""
    try:
        date_from, date_to = resolve_period(date_from, date_to)
    except StatsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await VisitService(db).stats(date_from, date_to)
