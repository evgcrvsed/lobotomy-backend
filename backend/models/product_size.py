from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class ProductSize(Base):
    __tablename__ = "product_sizes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(10), nullable=False)  # S, M, L, XL...
    # Замеры: {название столбца: значение}. Названия и порядок столбцов — в Product.size_columns,
    # незаполненных ключей здесь просто нет. Значения строковые: в них пишут не только
    # сантиметры («46-48», «one size», «~70cm»).
    measurements: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    sort_order: Mapped[int] = mapped_column(default=0)

    product: Mapped["Product"] = relationship(back_populates="sizes")
