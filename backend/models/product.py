from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Читаемый адрес карточки (/product/<slug>); уникальность обеспечивает индекс из main.py
    slug: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    material: Mapped[str | None] = mapped_column(String(200))
    density: Mapped[int | None] = mapped_column()
    # Цвет и вес нужны только для выгрузки в Google-таблицу: по ним владелец
    # собирает партию на отшив. Витрина их не показывает — но и не прячет,
    # в ответе API они есть, секрета в них нет.
    # Цвет заодно различает товары с одинаковым названием (две футболки разного
    # цвета — это два товара с общим именем, и на листе их путать нельзя).
    # Оба — свободный текст без разбора: это техническая пометка для отшива,
    # и в вес пишут что угодно («1.2», «~500 г», «пара 0,8»). Разбирать её
    # некому и незачем — значение просто ложится в ячейку таблицы как есть.
    color: Mapped[str | None] = mapped_column(String(100))
    weight: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[int | None] = mapped_column(nullable=False)
    # Порядок в каталоге: меньше — выше. Новым товарам ставится с запасом
    # (шаг 10), чтобы товар можно было вставить между двумя, ничего не перенумеровывая.
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    # Убран с витрины, но остаётся доступен по прямой ссылке и покупается как обычно.
    # Нужен, чтобы снимать распроданное с главной, не удаляя товар: на него ссылаются
    # позиции заказов, и удаление такого товара упирается во внешний ключ.
    is_hidden: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    # Шапка размерной сетки: названия столбцов замеров в порядке показа. Своя у каждого
    # товара — у брюк и футболки замеры называются по-разному. Задаётся в админке.
    size_columns: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    collection: Mapped["Collection"] = relationship(back_populates="products")
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order"
    )
    sizes: Mapped[list["ProductSize"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductSize.sort_order"
    )
