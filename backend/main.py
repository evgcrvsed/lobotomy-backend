import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.models import Base, DeliveryMethod, Product
from backend.routers import (
    AuthRouter,
    CollectionsRouter,
    DeliveryRouter,
    PaymentsRouter,
    ProductsRouter,
    UploadsRouter,
)
from backend.services import slugify
from backend.services.cdek_sync import poll_forever
from backend.services.product_service import ProductService


async def _seed_delivery_methods() -> None:
    """Способы доставки нужны для оформления заказа, поэтому при пустой таблице
    создаём стандартный набор. Цены и подписи потом правятся в админке."""
    initial = [
        ("cdek", "СДЭК", 450, "Индекс СДЭК", "Адрес пункта СДЭК", 1),
        ("post", "Почта России", 350, "Индекс Почты России", "Адрес отделения Почты России", 2),
        ("cis", "Страны СНГ", 750, "Индекс", "Адрес", 3),
    ]
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeliveryMethod))
        if result.scalars().first() is not None:
            return
        for code, label, price, index_label, point_label, order in initial:
            session.add(DeliveryMethod(
                code=code, label=label, price=price,
                index_label=index_label, point_label=point_label, sort_order=order,
            ))
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


async def _backfill_product_sort_order() -> None:
    """Расставляет порядок товарам, созданным до появления этой колонки: шаг 10.

    Работает ровно один раз — пока ни у одного товара порядок не задан.
    Как только в каталоге появился хоть один ненулевой номер, считаем разметку
    сделанной и больше не вмешиваемся: иначе выставленный вручную 0
    («в самое начало») на следующем перезапуске уехал бы в конец каталога.
    """
    async with AsyncSessionLocal() as session:
        already = await session.execute(select(Product.id).where(Product.sort_order != 0).limit(1))
        if already.first() is not None:
            return

        result = await session.execute(select(Product).order_by(Product.id))
        products = list(result.scalars())
        if not products:
            return
        # нумеруем в прежнем порядке (по id), чтобы каталог не перетасовался
        for i, product in enumerate(products, start=1):
            product.sort_order = i * ProductService.SORT_STEP
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all не меняет уже существующие таблицы — добавляем колонки сами
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS slug VARCHAR(200)"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_products_slug ON products (slug)"))
        await conn.execute(text("ALTER TABLE collections ADD COLUMN IF NOT EXISTS image VARCHAR(255)"))
        await conn.execute(
            text("ALTER TABLE collections ADD COLUMN IF NOT EXISTS is_hero BOOLEAN NOT NULL DEFAULT FALSE")
        )
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE")
        )
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS ip VARCHAR(64)"))
        for col, ddl in (
            ("phone", "VARCHAR(50)"),
            ("country", "VARCHAR(100)"),
            ("pickup_point", "VARCHAR(500)"),
        ):
            await conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {ddl}"))
        for col, ddl in (
            ("cdek_status_code", "VARCHAR(50)"),
            ("cdek_status_name", "VARCHAR(200)"),
            ("cdek_status_at", "TIMESTAMPTZ"),
            ("cdek_checked_at", "TIMESTAMPTZ"),
            ("confirmation_sent_at", "TIMESTAMPTZ"),
        ):
            await conn.execute(text(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {col} {ddl}"))
    await _seed_delivery_methods()
    await _backfill_product_slugs()
    await _backfill_product_sort_order()

    # Фоновый опрос СДЭК: сам решает, кого и когда проверять
    cdek_task = asyncio.create_task(poll_forever())
    try:
        yield
    finally:
        cdek_task.cancel()
        with suppress(asyncio.CancelledError):
            await cdek_task


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.include_router(ProductsRouter)
app.include_router(CollectionsRouter)
app.include_router(UploadsRouter)
app.include_router(AuthRouter)
app.include_router(PaymentsRouter)
app.include_router(DeliveryRouter)
