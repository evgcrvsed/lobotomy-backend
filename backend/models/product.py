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
    price: Mapped[int | None] = mapped_column(nullable=False)
    # Порядок в каталоге: меньше — выше. Новым товарам ставится с запасом
    # (шаг 10), чтобы товар можно было вставить между двумя, ничего не перенумеровывая.
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
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
