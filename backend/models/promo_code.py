from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class PromoCode(Base):
    """Промокод на скидку в процентах.

    Пока только заводится в админке — применение к заказу появится отдельно,
    под него здесь уже лежит счётчик использований.
    """

    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Хранится в верхнем регистре: покупатель вводит как придётся, а сравнивать
    # проще по одному написанию, чем городить регистронезависимый поиск
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    discount_percent: Mapped[int] = mapped_column(nullable=False)
    # Сколько раз промокод можно применить. Пусто — без ограничения
    max_activations: Mapped[int | None] = mapped_column()
    used_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    # Последний день, когда промокод работает, — включительно. Пусто — бессрочный.
    # Дата, а не момент времени: срок годности считается по календарю, и так
    # не приходится решать, в каком часовом поясе наступает полночь.
    expires_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
