from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class Visit(Base):
    """Заход на сайт с чужой площадки — одна строка на сессию посетителя.

    Откуда пришли, узнаём из document.referrer: браузер сам подставляет туда
    страницу, с которой по ссылке перешли. Разметки в адресе (utm_source и прочего)
    нет — ссылку на магазин кидают в чат или в шапку профиля как есть, и никто
    не станет дописывать к ней метки.

    Личного о посетителе не храним: ни полного адреса реферера с его параметрами,
    ни страницы входа — только площадка, с которой пришли.
    """

    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    # vk | telegram | instagram | youtube | tiktok | pinterest | x | google |
    # yandex | direct | other — см. SOURCE_RULES в services/visit_service.py
    source: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # Хост реферера как он есть («dzen.ru»). Нужен, чтобы разобрать «Другое»:
    # без него незнакомая площадка навсегда останется безымянной. У прямых заходов пусто.
    host: Mapped[str | None] = mapped_column(String(255))
    # Только для антиспама — в админку не отдаётся (см. VisitService.record)
    ip: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
