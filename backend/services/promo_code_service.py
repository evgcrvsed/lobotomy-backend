from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PromoCode
from backend.schemas.promo_code import PromoCodeCreate


class PromoCodeTakenError(Exception):
    pass


class PromoCodeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[PromoCode]:
        # свежие сверху: в админке чаще смотрят на только что заведённый
        result = await self.db.execute(select(PromoCode).order_by(PromoCode.id.desc()))
        return list(result.scalars().all())

    async def create(self, data: PromoCodeCreate) -> PromoCode:
        code = data.code.strip().upper()

        taken = await self.db.execute(select(PromoCode.id).where(PromoCode.code == code))
        if taken.first() is not None:
            raise PromoCodeTakenError(f"Промокод «{code}» уже есть")

        promo = PromoCode(
            code=code,
            discount_percent=data.discount_percent,
            max_activations=data.max_activations,
            expires_at=data.expires_at,
        )
        self.db.add(promo)
        await self.db.commit()
        await self.db.refresh(promo)
        return promo

    async def delete(self, promo_id: int) -> bool:
        promo = await self.db.get(PromoCode, promo_id)
        if promo is None:
            return False

        await self.db.delete(promo)
        await self.db.commit()
        return True
