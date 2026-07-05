from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class ProductSize(Base):
    __tablename__ = "product_sizes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(10), nullable=False)  # S, M, L, XL...
    # Замеры в сантиметрах; None — если замер не указан
    length: Mapped[int | None] = mapped_column()
    shoulder: Mapped[int | None] = mapped_column()
    chest: Mapped[int | None] = mapped_column()
    sleeve: Mapped[int | None] = mapped_column()
    sort_order: Mapped[int] = mapped_column(default=0)

    product: Mapped["Product"] = relationship(back_populates="sizes")
