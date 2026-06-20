from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Collection, Product, ProductImage
from backend.schemas.product import ProductCreate


class CollectionNotFoundError(Exception):
    pass


class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Product]:
        result = await self.db.execute(
            select(Product).options(selectinload(Product.images)).order_by(Product.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, product_id: int) -> Product | None:
        result = await self.db.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.images))
        )
        return result.scalar_one_or_none()

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
                sort_order=img.sort_order,
            ))

        await self.db.commit()
        return await self.get_by_id(product.id)

    async def update(self, product_id: int, data: ProductCreate) -> Product | None:
        product = await self.get_by_id(product_id)
        if product is None:
            return None

        collection = await self.db.get(Collection, data.collection_id)
        if collection is None:
            raise CollectionNotFoundError(f"Collection id={data.collection_id} not found")

        product.collection_id = data.collection_id
        product.name = data.name
        product.description = data.description
        product.material = data.material
        product.density = data.density
        product.price = data.price

        for img in list(product.images):
            await self.db.delete(img)
        await self.db.flush()

        for img_data in data.images:
            self.db.add(ProductImage(
                product_id=product.id,
                filename=img_data.filename,
                sort_order=img_data.sort_order,
            ))

        await self.db.commit()
        return await self.get_by_id(product_id)

    async def delete(self, product_id: int) -> bool:
        product = await self.db.get(Product, product_id)
        if product is None:
            return False
        await self.db.delete(product)
        await self.db.commit()
        return True
