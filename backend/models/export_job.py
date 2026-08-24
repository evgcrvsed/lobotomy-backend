from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base

# Текст ошибки в message обрезаем: в админке он показывается целиком,
# и простыня трейсбека там ничего не объясняет
MESSAGE_LIMIT = 500


class ExportJob(Base):
    """Заявка на выгрузку в Google-таблицу.

    Кнопку жмут в админке (это веб-процесс), а ходит в Google отдельный контейнер
    (backend/workers/sheets.py). Прямого канала между ними нет и заводить его незачем:
    база у процессов общая, поэтому кнопка просто кладёт сюда строку, а воркер её забирает.
    Заодно у выгрузки появляется история: видно, когда её запускали и чем кончилось.
    """

    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # pending — ждёт воркера, running — тот её взял, done/error — закончилась
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    # Итог для админки: «Листов: 7, новых строк: 12» или текст ошибки
    message: Mapped[str | None] = mapped_column(Text)
    rows_added: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
