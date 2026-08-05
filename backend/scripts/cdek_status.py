"""Диагностика автообновления статусов СДЭК.

Показывает по каждому заказу: попадает ли он в опрос, когда проверяли
последний раз и когда будет следующий. Отвечает на вопрос «почему статус
не обновился сам».

Запуск на сервере:
    docker compose exec backend python backend/scripts/cdek_status.py
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import Order
from backend.services.cdek_sync import CDEK_FINAL, TRACKED_STATUSES, _due_orders
from backend.services.cdek_service import is_configured


def _why_skipped(order: Order, now: datetime) -> str | None:
    """Причина, по которой заказ не попадает в автоопрос. None — попадает."""
    if order.delivery_method != "cdek":
        return f"доставка не СДЭК ({order.delivery_method})"
    if not order.tracking_number:
        return "нет трек-номера"
    if order.status not in TRACKED_STATUSES:
        return f"статус «{order.status}» — опрашиваются только {', '.join(TRACKED_STATUSES)}"
    if order.cdek_status_code in CDEK_FINAL:
        return f"финальный статус СДЭК ({order.cdek_status_code}) — больше не меняется"
    return None


async def main() -> None:
    now = datetime.now(timezone.utc)
    window = timedelta(minutes=settings.cdek_recheck_minutes)

    print("=== Настройки ===")
    print(f"  интеграция настроена : {is_configured()}")
    print(f"  проход опроса        : раз в {settings.cdek_poll_interval_minutes} мин")
    print(f"  один заказ не чаще   : раза в {settings.cdek_recheck_minutes} мин")
    print(f"  за проход максимум   : {settings.cdek_batch_limit} заказов")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(30))
        orders = list(result.scalars())

        print(f"\n=== Заказы (последние {len(orders)}) ===")
        for o in orders:
            reason = _why_skipped(o, now)
            print(f"\n  {o.number}  статус: {o.status}")
            print(f"    трек-номер     : {o.tracking_number or '—'}")
            print(f"    статус СДЭК    : {o.cdek_status_name or '—'} ({o.cdek_status_code or '—'})")
            if o.cdek_checked_at:
                прошло = now - o.cdek_checked_at
                следующий = o.cdek_checked_at + window
                осталось = следующий - now
                print(f"    проверяли      : {int(прошло.total_seconds() // 60)} мин назад")
                if reason is None:
                    print(
                        "    следующая      : "
                        + (
                            "в ближайший проход"
                            if осталось.total_seconds() <= 0
                            else f"через {int(осталось.total_seconds() // 60)} мин (окно перепроверки)"
                        )
                    )
            else:
                print("    проверяли      : ни разу")
            print(f"    в автоопросе   : {'да' if reason is None else 'НЕТ — ' + reason}")

        due = await _due_orders(db)
        print(f"\n=== Прямо сейчас в очередь попадают: {len(due)} ===")
        for o in due:
            print(f"  {o.number} ({o.tracking_number})")
        if not due:
            print("  (пусто — либо все недавно проверены, либо проверять нечего)")


if __name__ == "__main__":
    asyncio.run(main())
