from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.models import Collection, Product, ProductImage, ProductSize
from backend.schemas.product import ProductCreate


class CollectionNotFoundError(Exception):
    pass


class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Product]:
        result = await self.db.execute(
            select(Product)
            .options(selectinload(Product.images), selectinload(Product.sizes))
            .order_by(Product.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, product_id: int) -> Product | None:
        result = await self.db.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.images), selectinload(Product.sizes))
        )
        return result.scalar_one_or_none()

    def _add_sizes(self, product_id: int, data: ProductCreate) -> None:
        for i, size in enumerate(data.sizes):
            self.db.add(ProductSize(
                product_id=product_id,
                label=size.label,
                length=size.length,
                shoulder=size.shoulder,
                chest=size.chest,
                sleeve=size.sleeve,
                sort_order=i + 1,
            ))

    async def create(self, data: ProductCreate) -> Product:
        collection = await self.db.get(Collection, data.collection_id)
        if collection is None:
            raise CollectionNotFoundError(f"Collection id={data.collection_id} not found")

        product = Product(
            collection_id=data.collection_id,
            name=data.name,
            description=data.description,
            material=data.material,
            density=data.density,
            price=data.price,
        )
        self.db.add(product)
        await self.db.flush()

        for img in data.images:
            self.db.add(ProductImage(
                product_id=product.id,
                filename=img.filename,
                role=img.role,
                sort_order=img.sort_order,
            ))
        self._add_sizes(product.id, data)

        await self.db.commit()
        return await self.get_by_id(product.id)

    async def _delete_unused_files(self, filenames: list[str]) -> None:
        """Удаляет с диска файлы, на которые больше не ссылается ни один товар."""
        candidates = set(filenames)
        if not candidates:
            return
        result = await self.db.execute(
            select(ProductImage.filename).where(ProductImage.filename.in_(candidates))
        )
        still_used = set(result.scalars().all())
        for name in candidates - still_used:
            (settings.static_dir / "images" / name).unlink(missing_ok=True)

    async def update(self, product_id: int, data: ProductCreate) -> Product | None:
        product = await self.get_by_id(product_id)
        if product is None:
            return None

        collection = await self.db.get(Collection, data.collection_id)
        if collection is None:
            raise CollectionNotFoundError(f"Collection id={data.collection_id} not found")

        old_filenames = [img.filename for img in product.images]

        product.collection_id = data.collection_id
        product.name = data.name
        product.description = data.description
        product.material = data.material
        product.density = data.density
        product.price = data.price

        for img in list(product.images):
            await self.db.delete(img)
        for size in list(product.sizes):
            await self.db.delete(size)
        await self.db.flush()

        for img_data in data.images:
            self.db.add(ProductImage(
                product_id=product.id,
                filename=img_data.filename,
                role=img_data.role,
                sort_order=img_data.sort_order,
            ))
        self._add_sizes(product.id, data)

        await self.db.commit()
        await self._delete_unused_files(old_filenames)
        return await self.get_by_id(product_id)

    async def delete(self, product_id: int) -> bool:
        product = await self.get_by_id(product_id)
        if product is None:
            return False
        filenames = [img.filename for img in product.images]
        await self.db.delete(product)
        await self.db.commit()
        await self._delete_unused_files(filenames)
        return True
