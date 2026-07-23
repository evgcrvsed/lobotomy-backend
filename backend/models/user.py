from datetime import datetime

from sqlalchemy import Boolean, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Способ авторизации: email | vk | phone (телефон и соцсети — в планах)
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False)
    vk_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    full_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
