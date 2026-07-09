from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.models import Base, Collection, Product
from backend.routers import collections, products, uploads
from backend.services.slugs import slugify


async def _seed_collections() -> None:
    initial = [("Cardinal", "cardinal"), ("Gula", "gula"), ("Acedia", "acedia")]
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Collection))
        if result.scalars().first() is None:
            for name, slug in initial:
                session.add(Collection(name=name, slug=slug))
            await session.commit()


async def _backfill_product_slugs() -> None:
    """Генерирует адреса из названий для товаров, созданных до появления slug."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Product).where(Product.slug.is_(None)))
        products_without_slug = list(result.scalars())
        for product in products_without_slug:
            base = slugify(product.name)
            slug = base
            n = 2
            while True:
                taken = await session.execute(
                    select(Product.id).where(Product.slug == slug, Product.id != product.id)
                )
                if taken.first() is None:
                    break
                slug = f"{base}-{n}"
                n += 1
            product.slug = slug
        if products_without_slug:
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all не меняет уже существующие таблицы — добавляем колонки сами
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS slug VARCHAR(200)"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_products_slug ON products (slug)"))
        await conn.execute(text("ALTER TABLE collections ADD COLUMN IF NOT EXISTS image VARCHAR(255)"))
    await _seed_collections()
    await _backfill_product_slugs()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.include_router(products.router)
app.include_router(collections.router)
app.include_router(uploads.router)
