from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class EmailSendLog(Base):
    """Журнал отправленных писем с кодом входа.

    Нужен для защиты от спама: по нему считаем, сколько писем ушло
    с одного IP за период. Записи живут сутки, потом чистятся.
    """

    __tablename__ = "email_send_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
