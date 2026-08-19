from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.promo_code import PromoCodeCreate, PromoCodeResponse
from backend.services.auth_service import get_current_admin
from backend.services.promo_code_service import PromoCodeService, PromoCodeTakenError

router = APIRouter(prefix="/api/promo-codes", tags=["promo-codes"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]


# Весь список — только админу: иначе действующие промокоды можно было бы
# просто вычитать из открытого API
@router.get("/", response_model=list[PromoCodeResponse], dependencies=admin_only)
async def list_promo_codes(db: DbDep):
    return await PromoCodeService(db).list_all()


@router.post("/", response_model=PromoCodeResponse, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_promo_code(data: PromoCodeCreate, db: DbDep):
    try:
        return await PromoCodeService(db).create(data)
    except PromoCodeTakenError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.delete("/{promo_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_promo_code(promo_id: int, db: DbDep):
    if not await PromoCodeService(db).delete(promo_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Промокод не найден")
