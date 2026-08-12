from datetime import date

from pydantic import BaseModel


class SourceCount(BaseModel):
    """Сколько заходов пришло с одной площадки. source — ключ из SOURCE_RULES."""

    source: str
    visits: int


class OtherHost(BaseModel):
    """Незнакомая площадка из «Другого» — чтобы её было видно поимённо."""

    host: str
    visits: int


class TrafficStats(BaseModel):
    date_from: date
    date_to: date
    total: int
    sources: list[SourceCount]  # по убыванию числа заходов
    other_hosts: list[OtherHost]
