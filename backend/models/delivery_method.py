from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class DeliveryMethod(Base):
    """Способ доставки. Цену и подписи полей меняет админ, поэтому они в БД,
    а не в коде. Код (cdek/post/...) неизменен — на него ссылаются заказы."""

    __tablename__ = "delivery_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)  # «СДЭК»
    price: Mapped[int] = mapped_column(nullable=False)  # рубли
    # Подписи полей на оформлении — тоже настраиваемые
    index_label: Mapped[str] = mapped_column(String(100), nullable=False, default="Индекс")
    point_label: Mapped[str] = mapped_column(String(100), nullable=False, default="Адрес")
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
