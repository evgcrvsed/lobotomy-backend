from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class PaymentAttempt(Base):
    """Одна попытка оплаты — один вызов Init в Т-Банк.

    У заказа их может быть несколько: покупатель возвращается и жмёт «оплатить» снова,
    и банк каждый раз заводит новый PaymentId. Раньше в заказе хранился только последний,
    поэтому оплата по старой ссылке ссылалась на платёж, которого в базе уже не было —
    ровно тот случай, когда покупатель говорит «я оплатил, а вы не засчитали».
    """

    __tablename__ = "payment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True, nullable=False)
    # None — Init не дошёл до банка или был отклонён, PaymentId не выдан
    payment_id: Mapped[str | None] = mapped_column(String(50), index=True)
    amount: Mapped[int] = mapped_column(nullable=False)  # рубли, сумма заказа на момент попытки
    # new — ссылка выдана, ждём оплату; confirmed — по этому платежу пришло CONFIRMED;
    # failed — банк отклонил Init
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    error: Mapped[str | None] = mapped_column(Text)  # текст отказа Т-Банка
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship(back_populates="payment_attempts")


class PaymentNotification(Base):
    """Входящее уведомление от Т-Банка — пишем любое.

    В том числе с битой подписью и на несуществующий заказ: раньше такие уходили
    в print и терялись вместе с логами контейнера, а именно они и нужны, когда
    разбираешь спорную оплату через месяц.
    """

    __tablename__ = "payment_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    # заказ может не найтись — тогда остаётся только номер, как его прислал банк
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    order_number: Mapped[str | None] = mapped_column(String(40), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[str | None] = mapped_column(String(30))  # CONFIRMED, REJECTED, ...
    amount_kopecks: Mapped[int | None] = mapped_column()
    signature_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # засчитали ли как оплату; если нет — в note написано почему
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped["Order | None"] = relationship(back_populates="payment_notifications")
