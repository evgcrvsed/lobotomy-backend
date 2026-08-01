from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # Основная картинка коллекции — показывается сверху на страницах её товаров
    image: Mapped[str | None] = mapped_column(String(255))
    # Чья картинка стоит в самом верху главной страницы. Выбранная всегда одна:
    # при установке флага сервис снимает его со всех остальных коллекций.
    is_hero: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    products: Mapped[list["Product"]] = relationship(back_populates="collection")
