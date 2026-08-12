from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Order

# Заработком считаем только то, за что деньги пришли. Отменённые сюда не попадают
# и без этого (у них нет paid_at), но список статусов держим явно: так видно,
# что вручённый заказ — это тоже выручка, а не «уже закрытая» строка.
PAID_STATUSES = ("paid", "shipped", "ready", "delivered")

# Часовой пояс отчёта. Даты в БД хранятся в UTC, а владелец смотрит на них
# по-московски: без пересчёта ночная покупка уезжала бы во вчерашний день.
REPORT_TZ = "Europe/Moscow"

# Дальше какого размаха дневные столбцы превращаются в кашу — переходим
# на недели, потом на месяцы. Границы в днях.
WEEK_FROM_DAYS = 70
MONTH_FROM_DAYS = 400

# Год за раз — уже 12 столбцов по месяцам; больше отчёт не осилит осмысленно
MAX_RANGE_DAYS = 1100


class StatsError(Exception):
    pass


def pick_unit(date_from: date, date_to: date) -> str:
    """Шаг столбца по размаху периода: день / неделя / месяц."""
    days = (date_to - date_from).days + 1
    if days > MONTH_FROM_DAYS:
        return "month"
    if days > WEEK_FROM_DAYS:
        return "week"
    return "day"


def _next_bucket(start: date, unit: str) -> date:
    if unit == "day":
        return start + timedelta(days=1)
    if unit == "week":
        return start + timedelta(days=7)
    # месяц: первое число следующего
    return date(start.year + start.month // 12, start.month % 12 + 1, 1)


def _bucket_start(day: date, unit: str) -> date:
    """Начало корзины, в которую попадает дата. Совпадает с date_trunc в Postgres:
    неделя там начинается с понедельника."""
    if unit == "day":
        return day
    if unit == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


class StatsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def revenue(self, date_from: date, date_to: date) -> dict:
        """Доход за период: итоги и разбивка по корзинам для диаграммы.

        Дата заказа здесь — день оплаты, а не оформления: в отчёте о заработке
        важно, когда пришли деньги. Неоплаченные заказы в него не входят вовсе.
        """
        if date_from > date_to:
            raise StatsError("Начало периода позже его конца")
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise StatsError("Слишком длинный период — возьмите не больше трёх лет")

        unit = pick_unit(date_from, date_to)
        # paid_at лежит в UTC; переводим в часовой пояс отчёта и уже по местной
        # дате и режем период, и раскладываем по корзинам
        local_paid = func.timezone(REPORT_TZ, Order.paid_at)
        bucket = func.date_trunc(unit, local_paid)
        period = [
            Order.status.in_(PAID_STATUSES),
            Order.paid_at.is_not(None),
            local_paid >= date_from,
            # правая граница — начало следующего дня: иначе заказы за последний
            # день после полуночи-ноль-ноль в отчёт не попадут
            local_paid < date_to + timedelta(days=1),
        ]

        totals = await self.db.execute(
            select(
                func.coalesce(func.sum(Order.total), 0),
                func.coalesce(func.sum(Order.items_total), 0),
                func.coalesce(func.sum(Order.delivery_price), 0),
                func.count(Order.id),
            ).where(*period)
        )
        revenue, items_revenue, delivery_revenue, orders = totals.one()

        rows = await self.db.execute(
            select(
                bucket.label("bucket"),
                func.coalesce(func.sum(Order.total), 0),
                func.count(Order.id),
            )
            .where(*period)
            .group_by(bucket)
        )
        by_bucket = {row[0].date(): (row[1], row[2]) for row in rows}

        # пустые корзины тоже нужны: без них в диаграмме исчезнут дни без заказов,
        # и соседние столбцы окажутся рядом, будто продажи шли подряд
        points = []
        start = _bucket_start(date_from, unit)
        while start <= date_to:
            bucket_revenue, bucket_orders = by_bucket.get(start, (0, 0))
            points.append({"date": start, "revenue": bucket_revenue, "orders": bucket_orders})
            start = _next_bucket(start, unit)

        return {
            "date_from": date_from,
            "date_to": date_to,
            "unit": unit,
            "revenue": revenue,
            "items_revenue": items_revenue,
            "delivery_revenue": delivery_revenue,
            "orders": orders,
            "average_check": round(revenue / orders) if orders else 0,
            "points": points,
        }
