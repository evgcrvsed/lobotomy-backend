"""Журнал оплаты: что мы отправляли в Т-Банк и что он присылал в ответ.

Нужен для разбора спорных оплат («деньги списались, а заказ не оплачен»).
Ничего не решает по бизнес-логике — только фиксирует факты, поэтому его ошибки
не должны валить оплату: см. safe_* в роутере.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Order, PaymentAttempt, PaymentNotification

# Уведомлений от банка приходит заметно больше, чем попыток: он повторяет их,
# пока не увидит "OK". В карточке заказа показываем последние.
MAX_NOTIFICATIONS_SHOWN = 50


class PaymentLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_attempt(
        self, order: Order, payment_id: str | None, error: str | None = None
    ) -> PaymentAttempt:
        """Записывает вызов Init. error задан — банк отклонил, PaymentId не выдан."""
        attempt = PaymentAttempt(
            order_id=order.id,
            payment_id=payment_id,
            amount=order.total,
            status="failed" if error else "new",
            error=error,
        )
        self.db.add(attempt)
        await self.db.commit()
        return attempt

    async def record_manual(self, order: Order, note: str | None = None) -> None:
        """Оплата мимо банка, подтверждённая админом.

        В журнале она обязана быть видна: иначе заказ выглядит оплаченным
        без единого уведомления от Т-Банка, и через месяц не вспомнить, почему.
        """
        self.db.add(PaymentAttempt(
            order_id=order.id,
            payment_id=None,
            amount=order.total,
            status="manual",
            note=note or "Отмечено оплаченным вручную",
            confirmed_at=datetime.now(timezone.utc),
        ))
        await self.db.commit()

    async def record_notification(
        self,
        payload: dict,
        *,
        signature_ok: bool,
        order: Order | None,
        accepted: bool,
        note: str | None = None,
        ip: str | None = None,
    ) -> None:
        """Записывает входящее уведомление — включая то, которое мы не приняли."""
        amount = payload.get("Amount")
        payment_id = payload.get("PaymentId")
        number = payload.get("OrderId")
        self.db.add(PaymentNotification(
            order_id=order.id if order is not None else None,
            order_number=str(number)[:40] if number is not None else None,
            payment_id=str(payment_id)[:50] if payment_id is not None else None,
            status=str(payload.get("Status"))[:30] if payload.get("Status") else None,
            amount_kopecks=int(amount) if isinstance(amount, (int, str)) and str(amount).isdigit() else None,
            signature_ok=signature_ok,
            accepted=accepted,
            note=note,
            ip=ip,
            payload=payload,
        ))
        await self.db.commit()

    async def confirm_attempt(self, payment_id: str | None) -> None:
        """Отмечает попытку, по которой пришло CONFIRMED.

        Платёж мог быть создан ещё до появления журнала или по ссылке, которой у нас
        нет, — тогда отмечать нечего, факт оплаты всё равно виден в уведомлениях.
        """
        if not payment_id:
            return
        result = await self.db.execute(
            select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)
        )
        attempt = result.scalars().first()
        if attempt is None:
            return
        attempt.status = "confirmed"
        attempt.confirmed_at = datetime.now(timezone.utc)
        await self.db.commit()

    async def for_order(self, order: Order) -> tuple[list[PaymentAttempt], list[PaymentNotification]]:
        attempts = await self.db.execute(
            select(PaymentAttempt)
            .where(PaymentAttempt.order_id == order.id)
            .order_by(PaymentAttempt.id.desc())
        )
        # уведомления ищем и по номеру заказа: у пришедших на несуществующий
        # или уже удалённый заказ order_id пустой, но номер в них есть
        notifications = await self.db.execute(
            select(PaymentNotification)
            .where(
                (PaymentNotification.order_id == order.id)
                | (PaymentNotification.order_number == order.number)
            )
            .order_by(PaymentNotification.id.desc())
            .limit(MAX_NOTIFICATIONS_SHOWN)
        )
        return list(attempts.scalars()), list(notifications.scalars())
