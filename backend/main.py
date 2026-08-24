import json
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.errors import register_error_handlers, setup_logging
from backend.models import Base, DeliveryMethod, Order, PaymentAttempt, Product, SiteSetting
from backend.routers import (
    AuthRouter,
    CollectionsRouter,
    DeliveryRouter,
    ExportsRouter,
    PaymentsRouter,
    ProductsRouter,
    PromoCodesRouter,
    SettingsRouter,
    UploadsRouter,
    VisitsRouter,
)
from backend.services import slugify
from backend.services.product_service import ProductService


# Служебная отметка в site_settings: замеры уже переехали из колонок в JSON.
# В админку не попадёт — SettingsService отдаёт только ключи из KNOWN_SETTINGS.
SIZES_MIGRATED_FLAG = "sizes_migrated_to_json"
PAYMENT_LOG_FLAG = "payment_log_started"


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


async def _backfill_size_measurements() -> None:
    """Переносит замеры из колонок length/shoulder/chest/sleeve в JSON.

    Раньше набор замеров был зашит в модель и был числовым; теперь названия столбцов
    задаются в админке для каждого товара, а значения — строки (туда пишут и «46-48»,
    и «one size»). Числа переносим как есть: «cm» дописывает карточка товара.

    Работает ровно один раз: об этом говорит отметка в site_settings. Без неё пустая
    шапка неотличима от «ещё не переносили», и столбцы, снесённые в админке, возвращались
    бы из старых колонок при каждом перезапуске.
    """
    legacy = [("length", "Длина"), ("shoulder", "Плечо"), ("chest", "Грудь"), ("sleeve", "Рукав")]
    async with AsyncSessionLocal() as session:
        if await session.get(SiteSetting, SIZES_MIGRATED_FLAG) is not None:
            return

        # старые колонки мог уже удалить тот, кто убирал их руками после переноса
        present = await session.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'product_sizes' "
            "AND column_name IN ('length', 'shoulder', 'chest', 'sleeve')"
        ))
        available = {row[0] for row in present}

        if available:
            columns = ", ".join(f"s.{field}" for field, _ in legacy if field in available)
            # только товары с пустой шапкой: у остальных сетку уже правили руками
            rows = await session.execute(text(
                f"SELECT s.id, s.product_id, {columns} FROM product_sizes s "
                "JOIN products p ON p.id = s.product_id WHERE p.size_columns = '[]'::jsonb"
            ))
            by_product = defaultdict(list)
            for row in rows.mappings():
                by_product[row["product_id"]].append(row)

            for product_id, sizes in by_product.items():
                # столбец попадает в шапку, только если он заполнен хоть у одного размера
                used = [
                    title for field, title in legacy
                    if field in available and any(size[field] is not None for size in sizes)
                ]
                if not used:
                    continue
                await session.execute(
                    text("UPDATE products SET size_columns = CAST(:cols AS jsonb) WHERE id = :id"),
                    {"cols": json.dumps(used, ensure_ascii=False), "id": product_id},
                )
                for size in sizes:
                    measurements = {
                        title: str(size[field])
                        for field, title in legacy
                        if title in used and size[field] is not None
                    }
                    await session.execute(
                        text("UPDATE product_sizes SET measurements = CAST(:m AS jsonb) WHERE id = :id"),
                        {"m": json.dumps(measurements, ensure_ascii=False), "id": size["id"]},
                    )

        # отметку ставим и когда переносить было нечего — чистой базе перенос не нужен
        session.add(SiteSetting(key=SIZES_MIGRATED_FLAG, value="1"))
        await session.commit()


async def _backfill_payment_attempts() -> None:
    """Заводит попытку оплаты для заказов, созданных до появления журнала.

    Иначе у старых заказов карточка оплаты выглядела бы пустой, хотя PaymentId у них
    есть. Дату попытки берём от заказа — точнее уже не восстановить.
    """
    async with AsyncSessionLocal() as session:
        if await session.get(SiteSetting, PAYMENT_LOG_FLAG) is not None:
            return

        result = await session.execute(select(Order).where(Order.tinkoff_payment_id.is_not(None)))
        for order in result.scalars():
            session.add(PaymentAttempt(
                order_id=order.id,
                payment_id=order.tinkoff_payment_id,
                amount=order.total,
                status="confirmed" if order.paid_at is not None else "new",
                created_at=order.created_at,
                confirmed_at=order.paid_at,
            ))
        session.add(SiteSetting(key=PAYMENT_LOG_FLAG, value="1"))
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
        # снят с витрины, но доступен по прямой ссылке
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE")
        )
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS ip VARCHAR(64)"))
        # Размерная сетка: набор столбцов задаётся в админке, значения — свободный текст
        await conn.execute(text(
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS size_columns JSONB NOT NULL DEFAULT '[]'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE product_sizes ADD COLUMN IF NOT EXISTS measurements JSONB NOT NULL DEFAULT '{}'::jsonb"
        ))
        # комментарий к оплате, отмеченной админом вручную (перевод на карту)
        await conn.execute(text("ALTER TABLE payment_attempts ADD COLUMN IF NOT EXISTS note TEXT"))
        # старые колонки замеров больше не нужны, но сносим их не здесь, а руками —
        # после того, как _backfill_size_measurements перенесёт данные и сетка сойдётся
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
    await _backfill_size_measurements()
    await _backfill_payment_attempts()

    # Опрос статусов СДЭК живёт отдельным процессом (backend/workers/cdek.py):
    # рестарт API больше не обрывает проход, а логи опроса не мешаются с логом запросов.
    yield


setup_logging(settings.debug)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# Логирование ошибок и код обращения (X-Request-ID) — см. backend/errors.py
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    # без этого браузер не отдаёт фронтенду код обращения из заголовка ответа
    expose_headers=["X-Request-ID"],
)

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.include_router(ProductsRouter)
app.include_router(PromoCodesRouter)
app.include_router(CollectionsRouter)
app.include_router(UploadsRouter)
app.include_router(AuthRouter)
app.include_router(PaymentsRouter)
app.include_router(DeliveryRouter)
app.include_router(SettingsRouter)
app.include_router(ExportsRouter)
app.include_router(VisitsRouter)
