from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Collection


class CollectionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Collection]:
        result = await self.db.execute(select(Collection).order_by(Collection.id))
        return list(result.scalars().all())
