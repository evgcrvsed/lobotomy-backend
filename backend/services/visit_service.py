from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import Visit
from backend.services.stats_service import REPORT_TZ

# Куда относим заход. Метка — это одна часть хоста целиком: «google» ловит
# google.com, www.google.ru и google.co.uk, но не googleusercontent.com.
# Домены — для тех, у кого имя площадки в хосте не выделено («t.me», «youtu.be»).
#
# Ключи и порядок совпадают с TRAFFIC_SOURCES на фронте (src/constants.js) —
# оттуда берутся подписи и цвета секторов диаграммы. Площадок ровно восемь:
# столько на диаграмме различимых цветов, и порядок менять нельзя, не переспросив
# палитру (соседние по кругу сектора проверены на неразличимость при дальтонизме).
#
# Кого тут нет — Дзена, Pinterest, X и любого блога — попадает в «Другое»
# и показывается там поимённо по хосту: имя не теряется, теряется только свой цвет.
SOURCE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # ключ,         метки хоста,                    домены целиком
    ("vk",          ("vk", "vkontakte", "vkvideo"), ()),
    ("telegram",    ("telegram", "telegra"),        ("t.me",)),
    ("instagram",   ("instagram",),                 ()),
    ("youtube",     ("youtube",),                   ("youtu.be",)),
    ("tiktok",      ("tiktok",),                    ()),
    ("pinterest",   ("pinterest",),                 ()),
    ("google",      ("google",),                    ()),
    ("yandex",      ("yandex",),                    ("ya.ru",)),
)

# Заход без реферера: набрали адрес руками, открыли из закладок или перешли
# из приложения, которое реферер не отдаёт (так делает, например, Telegram)
DIRECT = "direct"
OTHER = "other"
# Переход внутри самого магазина — это не источник трафика, такие не пишем вовсе
INTERNAL = "internal"

# Антиспам: эндпоинт открыт всем, и без ограничения счётчик накрутили бы в одну
# строчку curl'ом. Живой посетитель шлёт одну запись на сессию вкладки.
VISIT_IP_LIMIT_10MIN = 20

# Сколько незнакомых площадок показывать в разборе «Другого»
OTHER_HOSTS_LIMIT = 10


def _host_of(url: str | None) -> str | None:
    """Хост из адреса реферера, без www и порта. Мусор и пустое — None."""
    if not url:
        return None
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:  # адрес, который urlsplit не разберёт
        return None
    if not host:
        return None
    host = host.lower().removeprefix("www.")
    return host[:255] or None


def _is_own(host: str, own_hosts: set[str]) -> bool:
    return any(host == own or host.endswith("." + own) for own in own_hosts if own)


def classify(referrer: str | None, own_hosts: set[str]) -> tuple[str, str | None]:
    """Реферер -> (источник, хост). Хост оставляем только у чужих площадок."""
    host = _host_of(referrer)
    if host is None:
        return DIRECT, None
    if _is_own(host, own_hosts):
        return INTERNAL, host

    labels = set(host.split("."))
    for source, marks, domains in SOURCE_RULES:
        if labels.intersection(marks):
            return source, host
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return source, host
    return OTHER, host


def own_hosts(request) -> set[str]:
    """Хосты самого магазина: свои переходы источником трафика не считаются.

    Берём и настроенный адрес сайта, и хост текущего запроса — в разработке
    это разные вещи (боевой домен в .env против localhost в браузере).
    """
    hosts = {_host_of(settings.site_url)}
    # Origin ставит браузер, подделать его со страницы нельзя; для POST он есть всегда
    hosts.add(_host_of(request.headers.get("origin")))
    hosts.add(request.url.hostname)
    return {h for h in hosts if h}


class VisitService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(self, referrer: str | None, own: set[str], ip: str | None) -> str:
        """Записывает заход. Возвращает источник — записанный или причину отказа.

        Ошибку наружу не поднимаем ни при каких данных: счётчик заходов не должен
        мешать человеку смотреть магазин, а фронт всё равно ответ не читает.
        """
        source, host = classify(referrer, own)
        if source == INTERNAL:
            return INTERNAL

        if ip:
            recent = await self.db.execute(
                select(func.count())
                .select_from(Visit)
                .where(Visit.ip == ip, Visit.created_at > datetime.now(timezone.utc) - timedelta(minutes=10))
            )
            if recent.scalar_one() >= VISIT_IP_LIMIT_10MIN:
                return "throttled"

        self.db.add(Visit(source=source, host=host, ip=ip))
        await self.db.commit()
        return source

    async def stats(self, date_from: date, date_to: date) -> dict:
        """Источники за период: сколько заходов с каждого и что скрыто в «Другом»."""
        # та же местная дата, что и в отчёте о заработке, — иначе два отчёта
        # за «один и тот же» период считали бы по разным суткам
        local = func.timezone(REPORT_TZ, Visit.created_at)
        period = [local >= date_from, local < date_to + timedelta(days=1)]

        rows = await self.db.execute(
            select(Visit.source, func.count(Visit.id))
            .where(*period)
            .group_by(Visit.source)
            .order_by(func.count(Visit.id).desc())
        )
        sources = [{"source": source, "visits": visits} for source, visits in rows]

        hosts = await self.db.execute(
            select(Visit.host, func.count(Visit.id))
            .where(*period, Visit.source == OTHER, Visit.host.is_not(None))
            .group_by(Visit.host)
            .order_by(func.count(Visit.id).desc())
            .limit(OTHER_HOSTS_LIMIT)
        )

        return {
            "date_from": date_from,
            "date_to": date_to,
            "total": sum(s["visits"] for s in sources),
            "sources": sources,
            "other_hosts": [{"host": host, "visits": visits} for host, visits in hosts],
        }
