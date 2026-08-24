"""Синхронизация проданных позиций с Google-таблицей.

Лист — товар, строка — заказ, в котором этот товар купили. Нужно это не для
отчётности, а для работы: по листу владелец заказывает отшив и прямо в нём
ведёт отметку «Не пошито / Пошито».

Отсюда главное правило: выгрузка не переписывает лист, а сверяется с ним.
Незнакомый заказ дописывает, знакомый — обновляет только в наших столбцах
(появился трек, поправили адрес). Status, «Цвет» и «Вес» принадлежат человеку
и не трогаются никогда. Отметок «выгружено» в базе нет: что уже в таблице,
знает сама таблица — по столбцу Order ID. Поэтому кнопку можно жать сколько
угодно, и заказ от этого не задвоится.

Задачи ставит админка через таблицу export_jobs, забирает их отдельный процесс
(backend/workers/sheets.py). Здесь — и сборка строк, и цикл разбора очереди.
"""

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import DeliveryMethod, ExportJob, Order
from backend.models.export_job import MESSAGE_LIMIT
from backend.services.sheets_service import GoogleSheet, sheet_title
from backend.services.stats_service import REPORT_TZ

# Выгружаем то, за что деньги пришли: неоплаченные и брошенные заказы отшивать
# незачем. Тот же набор, что и у выручки в админке (stats_service.PAID_STATUSES).
EXPORTED_STATUSES = ("paid", "shipped", "ready", "delivered")

# Сводный лист для заказов, в которых больше одного товара. Лист товара отвечает
# на вопрос «сколько футболок слать на отшив» и потому получает только футболку;
# но заказ из футболки и шорт после этого виден лишь по кускам на разных листах.
# «Мультизаказ» собирает такой заказ целиком — чтобы было видно, что человеку
# уходит не одна вещь и посылку надо собрать из нескольких партий.
MULTI_ORDER_TITLE = "Мультизаказ"
MULTI_ORDER_MIN = 2  # с какого числа разных товаров заказ считается сборным


class SheetsNotConfigured(Exception):
    pass


def configuration_problem() -> str | None:
    """Человеческая причина, по которой выгрузка невозможна. None — всё на месте."""
    if not settings.google_sheets_id:
        return "не задан GOOGLE_SHEETS_ID"
    if not settings.google_sheets_key_file.exists():
        return f"нет файла ключа {settings.google_sheets_key_file}"
    return None


def _address(order: Order) -> str:
    parts = [order.country, order.city, order.address, order.postal_code, order.pickup_point]
    return ", ".join(p for p in parts if p)


def _size_cell(item) -> str:
    """Размер позиции. Количество дописываем сюда же — отдельного столбца нет."""
    size = item.size or ""
    if item.qty > 1:
        return f"{size} × {item.qty}" if size else f"× {item.qty}"
    return size


def _order_date(order: Order) -> str:
    """Дата заказа по-московски: в БД она в UTC, и ночная покупка иначе
    уезжала бы во вчерашний день — та же оговорка, что в отчётах (stats_service)."""
    if order.created_at is None:
        return ""
    return order.created_at.astimezone(ZoneInfo(REPORT_TZ)).strftime("%Y-%m-%d")


def build_pages(orders: list[Order], delivery_labels: dict[str, str]) -> dict[str, list[dict]]:
    """Раскладывает заказы по листам: {название листа: [строки]}.

    Позиции одного товара внутри одного заказа сводим в одну строку. Иначе заказ,
    где взяли одну и ту же футболку в двух размерах, дал бы две неотличимые строки
    (ключ строки — заказ и товар), и вторую отбросила бы проверка на дубль.
    Размеры перечисляем через запятую, «Заплачено» суммируем.

    Столбцы Status, «Цвет» и «Вес» тут не заполняются вовсе: их ведёт владелец
    руками. Новой строке начальное «Не пошито» проставит сам GoogleSheet, а
    дальше эти ячейки — не наше дело.

    Заказ, в котором больше одного товара, дополнительно попадает целиком
    на сводный лист «Мультизаказ» — см. MULTI_ORDER_TITLE.
    """
    pages: dict[str, list[dict]] = defaultdict(list)
    for order in orders:
        by_product: dict[str, list] = defaultdict(list)
        for item in order.items:
            by_product[item.name].append(item)

        # заказ из нескольких разных товаров дублируем на сводный лист целиком
        multi = len(by_product) >= MULTI_ORDER_MIN

        for name, items in by_product.items():
            sizes = [s for s in (_size_cell(i) for i in items) if s]
            row = {
                "Order ID": order.number,
                "Дата заказа": _order_date(order),
                "Товар": name,
                "Размер": ", ".join(sizes),
                "Заплачено": sum(i.price * i.qty for i in items),
                "ФИО": order.full_name or "",
                "Телефон": order.phone or "",
                "Почта": order.email,
                "Адрес доставки": _address(order),
                "Способ доставки": delivery_labels.get(order.delivery_method, order.delivery_method),
                "Трек отправки": order.tracking_number or "",
            }
            # На лист товара идёт только его позиция — иначе по листу «Футболка»
            # нельзя было бы посчитать, сколько футболок шить.
            pages[sheet_title(name)].append(row)
            if multi:
                # тот же самый dict, а не копия: строку из него никто не меняет
                pages[MULTI_ORDER_TITLE].append(row)

    # на сводном листе держим позиции одного заказа рядом
    if MULTI_ORDER_TITLE in pages:
        pages[MULTI_ORDER_TITLE].sort(key=lambda r: (r["Дата заказа"], r["Order ID"], r["Товар"]))
    return pages


async def collect_pages(db: AsyncSession) -> dict[str, list[dict]]:
    """Готовит строки для выгрузки. В Google при этом не ходим — только читаем базу."""
    methods = await db.execute(select(DeliveryMethod))
    delivery_labels = {m.code: m.label for m in methods.scalars()}

    result = await db.execute(
        select(Order)
        .where(Order.status.in_(EXPORTED_STATUSES))
        .options(selectinload(Order.items))
        .order_by(Order.created_at)  # в таблице строки лягут в порядке продаж
    )
    return build_pages(list(result.scalars()), delivery_labels)


def _push_sync(pages: dict[str, list[dict]]) -> tuple[int, int, int]:
    """Синхронная часть: gspread блокирует поток, поэтому её зовут в to_thread.

    Возвращает (сколько листов прошли, добавлено строк, обновлено строк).
    """
    sheet = GoogleSheet(settings.google_sheets_key_file, settings.google_sheets_id)
    added = updated = 0
    titles = sorted(pages)
    for i, title in enumerate(titles):
        page_added, page_updated = sheet.sync_orders(title, pages[title])
        added += page_added
        updated += page_updated
        # пауза между листами: Sheets API считает запросы, а не строки
        if i + 1 < len(titles):
            time.sleep(settings.sheets_request_delay_seconds)
    return len(titles), added, updated


async def export_all() -> tuple[int, int, int]:
    """Полная синхронизация. Возвращает (листов, добавлено, обновлено)."""
    problem = configuration_problem()
    if problem is not None:
        raise SheetsNotConfigured(problem)

    async with AsyncSessionLocal() as db:
        pages = await collect_pages(db)

    if not pages:
        return 0, 0, 0
    return await asyncio.to_thread(_push_sync, pages)


async def _claim_job(db: AsyncSession) -> ExportJob | None:
    """Берёт из очереди самую старую невыполненную задачу и помечает её начатой."""
    result = await db.execute(
        select(ExportJob).where(ExportJob.status == "pending").order_by(ExportJob.id).limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()
    return job


async def run_pending_job() -> bool:
    """Разбирает одну задачу из очереди. False — очередь пуста."""
    async with AsyncSessionLocal() as db:
        job = await _claim_job(db)
        if job is None:
            return False

        print(f"[sheets] задача #{job.id}: начали выгрузку")
        try:
            pages, added, updated = await export_all()
        except asyncio.CancelledError:
            # Остановка контейнера на середине: возвращаем задачу в очередь,
            # чтобы после перезапуска её доделали, а не потеряли
            job.status = "pending"
            job.started_at = None
            await db.commit()
            raise
        except Exception as e:  # noqa: BLE001 — в задачу пишем любую причину, цикл живёт дальше
            job.status = "error"
            job.message = f"{type(e).__name__}: {e}"[:MESSAGE_LIMIT]
            print(f"[sheets] задача #{job.id}: ошибка — {job.message}")
        else:
            job.status = "done"
            job.rows_added = added
            job.message = f"листов {pages}, новых заказов {added}, обновлено {updated}"
            print(f"[sheets] задача #{job.id}: {job.message}")

        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return True


async def reset_stale_jobs() -> None:
    """Задачи, застрявшие в running после падения воркера, закрываем с ошибкой.

    Иначе админка вечно показывала бы «идёт выгрузка»: тот, кто её выполнял,
    уже не существует, а сама по себе строка не изменится.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(ExportJob)
            .where(ExportJob.status == "running")
            .values(
                status="error",
                message="Выгрузка прервана перезапуском — запустите ещё раз",
                finished_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        if result.rowcount:
            print(f"[sheets] закрыто незавершённых задач: {result.rowcount}")


async def poll_forever() -> None:
    """Цикл разбора очереди: живёт, пока живёт контейнер."""
    print(
        f"[sheets] жду задачи на выгрузку, проверка раз в "
        f"{settings.sheets_poll_interval_seconds} с"
    )
    while True:
        try:
            # пока задачи есть — разбираем подряд, не досыпая между ними
            while await run_pending_job():
                pass
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — разовый сбой базы не должен ронять цикл
            print(f"[sheets] сбой очереди: {e}")
        await asyncio.sleep(settings.sheets_poll_interval_seconds)
