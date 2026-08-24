"""Синхронизация проданных позиций с Google-таблицей.

Лист — товар, строка — заказ, в котором этот товар купили. Нужно это не для
отчётности, а для работы: по листу владелец заказывает отшив и прямо в нём
ведёт отметку «Не пошито / Пошито».

Отсюда главное правило: выгрузка не переписывает лист вслепую, а сверяется
с ним. Отметка о пошиве (Status) переезжает к своей строке по ключу и никогда
не затирается; строки, которых в выгрузке уже нет, не удаляются, а сдвигаются
вниз. Отметок «выгружено» в базе нет: что уже в таблице, знает сама таблица.
Поэтому кнопку можно жать сколько угодно, и заказ от этого не задвоится.

Строки на листе товара идут по размеру, и между размерами лежит пустая строка:
лист читают, чтобы понять, сколько чего слать на отшив, и группы должны быть
видны глазами. На сводном листе та же роль у номера заказа — там рядом должны
стоять позиции одного человека.

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
from backend.models import DeliveryMethod, ExportJob, Order, Product
from backend.models.export_job import MESSAGE_LIMIT
from backend.services.sheets_service import GoogleSheet, sheet_title, size_sort_key
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


def _size_cell(size: str | None, qty: int) -> str:
    """Размер позиции. Количество дописываем сюда же — отдельного столбца нет.

    На ключ строки количество не влияет (см. size_group): доложили ещё одну
    футболку того же размера — это та же строка, а не новая.
    """
    size = size or ""
    if qty > 1:
        return f"{size} × {qty}" if size else f"× {qty}"
    return size


def _order_date(order: Order) -> str:
    """Дата заказа по-московски: в БД она в UTC, и ночная покупка иначе
    уезжала бы во вчерашний день — та же оговорка, что в отчётах (stats_service)."""
    if order.created_at is None:
        return ""
    return order.created_at.astimezone(ZoneInfo(REPORT_TZ)).strftime("%Y-%m-%d")


def build_pages(
    orders: list[Order],
    delivery_labels: dict[str, str],
    products: dict[int, Product],
) -> dict[str, list[dict]]:
    """Раскладывает заказы по листам: {название листа: [строки]}.

    Строка — это один размер одного товара из одного заказа. Раньше позиции
    товара сводились в одну строку («M, L»), но лист читают по размерам —
    в таком виде по нему не посчитать, сколько шить каждого. Поэтому размеры
    разъехались по своим строкам; количество одного размера по-прежнему
    в ячейке размера («M × 2»), отдельного столбца под него нет.

    Группируем по товару, а не по одному названию: две футболки разного цвета
    названы одинаково, и сливать их нельзя — шьются они порознь.

    «Цвет» и «Вес» берём из карточки товара; название — из позиции заказа, потому
    что там оно снято на момент покупки и не меняется задним числом. «Заплачено» —
    сумма по этой строке, «Стоимость доставки» и «Итог» — общие по заказу, они
    повторяются во всех его строках. Status не заполняем вовсе: начальное
    «Не пошито» проставит новой строке сам GoogleSheet.

    Заказ, в котором больше одного товара, дополнительно попадает целиком
    на сводный лист «Мультизаказ» — см. MULTI_ORDER_TITLE.
    """
    pages: dict[str, list[dict]] = defaultdict(list)
    for order in orders:
        # Ключ — товар и размер. Товар, а не одно название: у разных товаров имя
        # может совпасть. product_id пуст у позиций, чей товар успели удалить, —
        # такие сводим по имени, цвет и вес для них взять всё равно неоткуда.
        # Две позиции с одним размером (админ дозаказал) складываются по количеству.
        by_line: dict[tuple, list] = defaultdict(list)
        for item in order.items:
            by_line[(item.product_id, item.name, item.size or "")].append(item)

        # заказ из нескольких разных ТОВАРОВ (а не размеров) — сборный
        distinct_products = {(product_id, name) for product_id, name, _ in by_line}
        multi = len(distinct_products) >= MULTI_ORDER_MIN

        for (product_id, name, size), items in by_line.items():
            product = products.get(product_id)
            qty = sum(i.qty for i in items)
            row = {
                "Order ID": order.number,
                "Дата заказа": _order_date(order),
                "Товар": name,
                "Цвет": (product.color or "") if product else "",
                "Вес": (product.weight or "") if product else "",
                "Размер": _size_cell(size, qty),
                "Заплачено": sum(i.price * i.qty for i in items),
                "Стоимость доставки": order.delivery_price,
                "Итог": order.total,
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

    for title, rows in pages.items():
        if title == MULTI_ORDER_TITLE:
            # сводный лист читают по заказам — держим позиции одного рядом
            rows.sort(key=lambda r: (r["Дата заказа"], r["Order ID"], r["Товар"], r["Цвет"]))
        else:
            # лист товара читают по размерам: сначала все S, потом все M...
            rows.sort(key=lambda r: (size_sort_key(r["Размер"]), r["Цвет"], r["Дата заказа"]))
    return pages


async def collect_pages(db: AsyncSession) -> dict[str, list[dict]]:
    """Готовит строки для выгрузки. В Google при этом не ходим — только читаем базу."""
    methods = await db.execute(select(DeliveryMethod))
    delivery_labels = {m.code: m.label for m in methods.scalars()}

    # Цвет и вес живут в карточке товара, а не в позиции заказа: их завели ради
    # отшива уже после того, как часть заказов была оформлена, и снимка на момент
    # покупки у старых позиций просто нет. Значит, берём текущее значение.
    catalog = await db.execute(select(Product))
    products = {p.id: p for p in catalog.scalars()}

    result = await db.execute(
        select(Order)
        .where(Order.status.in_(EXPORTED_STATUSES))
        .options(selectinload(Order.items))
        .order_by(Order.created_at)  # в таблице строки лягут в порядке продаж
    )
    return build_pages(list(result.scalars()), delivery_labels, products)


def _push_sync(pages: dict[str, list[dict]]) -> tuple[int, int, int]:
    """Синхронная часть: gspread блокирует поток, поэтому её зовут в to_thread.

    Возвращает (сколько листов прошли, добавлено строк, обновлено строк).
    """
    sheet = GoogleSheet(settings.google_sheets_key_file, settings.google_sheets_id)
    added = updated = 0
    titles = sorted(pages)
    for i, title in enumerate(titles):
        # чем отделять группы пустой строкой: на листе товара это размер,
        # на сводном — заказ (его позиции должны стоять вместе)
        group_header = "Order ID" if title == MULTI_ORDER_TITLE else "Размер"
        page_added, page_updated = sheet.sync_orders(title, pages[title], group_header)
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
