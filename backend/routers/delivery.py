from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import DeliveryMethod
from backend.schemas.delivery import DeliveryMethodResponse, DeliveryMethodUpdate
from backend.services.auth_service import get_current_admin

router = APIRouter(prefix="/api/delivery", tags=["delivery"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]


@router.get("/", response_model=list[DeliveryMethodResponse])
async def list_delivery_methods(db: DbDep):
    result = await db.execute(select(DeliveryMethod).order_by(DeliveryMethod.sort_order))
    return list(result.scalars())


@router.put("/{code}", response_model=DeliveryMethodResponse, dependencies=admin_only)
async def update_delivery_method(code: str, data: DeliveryMethodUpdate, db: DbDep):
    result = await db.execute(select(DeliveryMethod).where(DeliveryMethod.code == code))
    method = result.scalar_one_or_none()
    if method is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Способ доставки не найден")

    method.label = data.label.strip()
    method.price = data.price
    method.index_label = data.index_label.strip()
    method.point_label = data.point_label.strip()
    await db.commit()
    await db.refresh(method)
    return method
