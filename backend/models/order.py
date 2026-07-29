from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Неугадываемый номер: показывается покупателю, идёт в Т-Банк как OrderId,
    # по нему же публичный просмотр гостевого заказа.
    number: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    # Пусто = гостевой заказ. При входе с той же почтой заказ «прилипает» к пользователю.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)

    # Контакты и доставка
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    delivery_method: Mapped[str] = mapped_column(String(20), nullable=False)  # cdek | post | cis
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(500))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    pickup_point: Mapped[str | None] = mapped_column(String(500))

    # Суммы (в рублях)
    items_total: Mapped[int] = mapped_column(nullable=False)
    delivery_price: Mapped[int] = mapped_column(nullable=False)
    total: Mapped[int] = mapped_column(nullable=False)

    # pending | paid | shipped | ready | delivered | cancelled
    # После shipped статус ведёт СДЭК — см. services/cdek_sync.py
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    tinkoff_payment_id: Mapped[str | None] = mapped_column(String(50))
    tracking_number: Mapped[str | None] = mapped_column(String(100))  # админ впишет позже
    ip: Mapped[str | None] = mapped_column(String(64), index=True)  # для антиспама и разбора спорных заказов

    # Данные СДЭК по трек-номеру
    cdek_status_code: Mapped[str | None] = mapped_column(String(50))
    cdek_status_name: Mapped[str | None] = mapped_column(String(200))  # человеческая подпись от СДЭК
    cdek_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда СДЭК его поставил
    cdek_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда мы спрашивали

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """Снимок позиции на момент покупки — не зависит от последующих изменений товара."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    size: Mapped[str | None] = mapped_column(String(20))
    price: Mapped[int] = mapped_column(nullable=False)  # рубли, на момент покупки
    qty: Mapped[int] = mapped_column(nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
