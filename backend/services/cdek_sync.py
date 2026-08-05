"""Автообновление статусов заказов по данным СДЭК.

Опрашиваем только те заказы, где есть смысл: доставка СДЭК, вписан трек-номер
и заказ ещё в пути. Каждый заказ дёргаем не чаще cdek_recheck_minutes,
за один проход — не больше cdek_batch_limit штук с паузой между запросами.
Так лимиты СДЭК не задеваем даже при сотнях заказов, а на 429 весь опрос
встаёт на паузу.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import Order
from backend.services.cdek_service import (
    CdekError,
    CdekNotConfigured,
    CdekRateLimited,
    fetch_order,
    is_configured,
    latest_status,
    parse_cdek_datetime,
)

# Коды СДЭК -> наш статус заказа.
# Всё, чего здесь нет (транзит, склады, перевозчики) — это «в пути», то есть shipped.
CDEK_DELIVERED = {
    "DELIVERED",  # вручен получателю
    "POSTOMAT_RECEIVED",  # изъят из постамата клиентом
}
CDEK_READY = {
    "ACCEPTED_AT_PICK_UP_POINT",  # принят на склад до востребования
    "ACCEPTED_AT_WAREHOUSE_ON_DEMAND",
    "POSTOMAT_POSTED",  # заложен в постамат
}
# Конечные коды: дальше у СДЭК ничего не изменится, опрашивать больше нечего.
# NOT_DELIVERED сюда НЕ входит — курьер приедет повторно, статус ещё поменяется.
CDEK_FINAL = CDEK_DELIVERED | {
    "INVALID",  # некорректный заказ
    "REMOVED",  # заказ удалён у СДЭК
}

# Статусы заказа, которые ещё имеет смысл проверять
TRACKED_STATUSES = ("paid", "shipped", "ready")

# Общая пауза после 429 — на весь опрос, а не на отдельный заказ
_paused_until: datetime | None = None


def status_from_cdek(code: str | None) -> str:
    if code in CDEK_DELIVERED:
        return "delivered"
    if code in CDEK_READY:
        return "ready"
    return "shipped"


def apply_entity(order: Order, entity: dict) -> bool:
    """Переносит текущий статус СДЭК в заказ. True — что-то изменилось."""
    status = latest_status(entity)
    if status is None:
        return False

    code = status.get("code")
    before = (order.status, order.cdek_status_code)

    order.cdek_status_code = code
    order.cdek_status_name = status.get("name")
    order.cdek_status_at = parse_cdek_datetime(status.get("date_time"))
    order.status = status_from_cdek(code)

    return before != (order.status, order.cdek_status_code)


async def sync_order(order: Order, client: httpx.AsyncClient) -> bool:
    """Обновляет один заказ. Коммит — на вызывающей стороне."""
    entity = await fetch_order(order.tracking_number, client)
    order.cdek_checked_at = datetime.now(timezone.utc)
    if entity is None:
        # трек-номер не найден у СДЭК (опечатка или ещё не завели заказ) —
        # время проверки всё равно записали, чтобы не долбить каждую минуту
        return False
    return apply_entity(order, entity)


async def _due_orders(db: AsyncSession) -> list[Order]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.cdek_recheck_minutes)
    result = await db.execute(
        select(Order)
        .where(
            Order.delivery_method == "cdek",
            Order.tracking_number.is_not(None),
            Order.tracking_number != "",
            Order.status.in_(TRACKED_STATUSES),
            # Вручён / удалён у СДЭК — статус финальный, больше не дёргаем.
            # Условие по коду СДЭК, а не только по нашему статусу: так заказ
            # выпадает из опроса даже если наш статус кто-то поправит руками.
            or_(
                Order.cdek_status_code.is_(None),
                Order.cdek_status_code.not_in(CDEK_FINAL),
            ),
            or_(Order.cdek_checked_at.is_(None), Order.cdek_checked_at < cutoff),
        )
        # сначала те, кого не проверяли ни разу, потом самые «залежавшиеся»
        .order_by(Order.cdek_checked_at.asc().nullsfirst())
        .limit(settings.cdek_batch_limit)
    )
    return list(result.scalars())


async def sync_due_orders() -> dict:
    """Один проход опроса. Возвращает статистику для лога."""
    global _paused_until

    if not is_configured():
        return {"skipped": "не настроен СДЭК"}

    now = datetime.now(timezone.utc)
    if _paused_until and _paused_until > now:
        return {"skipped": f"пауза после 429 до {_paused_until:%H:%M}"}

    checked = 0
    changed = 0
    async with AsyncSessionLocal() as db:
        orders = await _due_orders(db)
        if not orders:
            # нечего проверять — но это не то же самое, что «опрос не работает»,
            # поэтому в лог всё равно пишем (см. poll_forever)
            return {"checked": 0, "changed": 0, "note": "нет заказов к проверке"}

        async with httpx.AsyncClient(timeout=25) as client:
            for i, order in enumerate(orders):
                try:
                    if await sync_order(order, client):
                        changed += 1
                    checked += 1
                except CdekRateLimited:
                    _paused_until = now + timedelta(minutes=settings.cdek_backoff_minutes)
                    print(f"[cdek] 429 — опрос на паузе до {_paused_until:%H:%M}")
                    break
                except (CdekNotConfigured, CdekError) as e:
                    print(f"[cdek] заказ {order.number}: {e}")
                    break  # СДЭК недоступен целиком — остальные ждут следующего прохода

                # пауза между запросами, но не после последнего
                if i + 1 < len(orders):
                    await asyncio.sleep(settings.cdek_request_delay_seconds)

        await db.commit()

    return {"checked": checked, "changed": changed}


async def poll_forever() -> None:
    """Фоновый цикл: запускается вместе с приложением и живёт до остановки."""
    if not is_configured():
        print("[cdek] автообновление статусов выключено (нет CDEK_CLIENT_ID)")
        return

    print(
        f"[cdek] автообновление статусов включено: проход раз в "
        f"{settings.cdek_poll_interval_minutes} мин, один заказ не чаще раза "
        f"в {settings.cdek_recheck_minutes} мин"
    )
    while True:
        try:
            stats = await sync_due_orders()
            # Пишем в лог каждый проход, даже пустой: иначе по молчанию нельзя
            # понять, опрос жив и делать нечего — или он вообще не работает.
            if stats.get("skipped"):
                print(f"[cdek] проход пропущен: {stats['skipped']}")
            elif stats.get("checked"):
                print(f"[cdek] проверено {stats['checked']}, обновлено {stats['changed']}")
            else:
                print(f"[cdek] {stats.get('note', 'проверять нечего')}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # цикл не должен умирать от разовой ошибки
            print(f"[cdek] сбой опроса: {e}")
        await asyncio.sleep(settings.cdek_poll_interval_minutes * 60)
