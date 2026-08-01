from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class SiteSetting(Base):
    """Тексты и мелкие настройки витрины, которые правит админ.

    Ключ-значение, а не колонка на каждую настройку: добавить новый
    редактируемый текст можно, не трогая схему БД.
    """

    __tablename__ = "site_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
