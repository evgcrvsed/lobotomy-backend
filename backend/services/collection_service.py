import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Collection, Product

# Транслитерация для генерации slug из русских названий
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(name: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "collection"


class CollectionNameTakenError(Exception):
    pass


class CollectionNotEmptyError(Exception):
    pass


class CollectionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Collection]:
        result = await self.db.execute(select(Collection).order_by(Collection.id))
        return list(result.scalars().all())

    async def _name_taken(self, name: str, exclude_id: int | None = None) -> bool:
        query = select(Collection.id).where(func.lower(Collection.name) == name.lower())
        if exclude_id is not None:
            query = query.where(Collection.id != exclude_id)
        result = await self.db.execute(query)
        return result.first() is not None

    async def _unique_slug(self, name: str, exclude_id: int | None = None) -> str:
        base = slugify(name)
        slug = base
        n = 2
        while True:
            query = select(Collection.id).where(Collection.slug == slug)
            if exclude_id is not None:
                query = query.where(Collection.id != exclude_id)
            result = await self.db.execute(query)
            if result.first() is None:
                return slug
            slug = f"{base}-{n}"
            n += 1

    async def create(self, name: str) -> Collection:
        if await self._name_taken(name):
            raise CollectionNameTakenError(f"Коллекция «{name}» уже существует")

        collection = Collection(name=name, slug=await self._unique_slug(name))
        self.db.add(collection)
        await self.db.commit()
        await self.db.refresh(collection)
        return collection

    async def rename(self, collection_id: int, name: str) -> Collection | None:
        collection = await self.db.get(Collection, collection_id)
        if collection is None:
            return None
        if await self._name_taken(name, exclude_id=collection_id):
            raise CollectionNameTakenError(f"Коллекция «{name}» уже существует")

        collection.name = name
        collection.slug = await self._unique_slug(name, exclude_id=collection_id)
        await self.db.commit()
        await self.db.refresh(collection)
        return collection

    async def delete(self, collection_id: int) -> bool:
        collection = await self.db.get(Collection, collection_id)
        if collection is None:
            return False

        result = await self.db.execute(
            select(func.count()).select_from(Product).where(Product.collection_id == collection_id)
        )
        products_count = result.scalar_one()
        if products_count:
            raise CollectionNotEmptyError(
                f"В коллекции {products_count} товар(ов) — сначала перенесите или удалите их"
            )

        await self.db.delete(collection)
        await self.db.commit()
        return True
