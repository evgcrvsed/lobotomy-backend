"""Клиент API СДЭК: токен, заказ по трек-номеру, разбор статусов.

Токен живёт час, поэтому держим его в памяти процесса и перевыпускаем
только когда он кончается — иначе на каждый заказ уходило бы два запроса.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from backend.config import settings


class CdekError(Exception):
    """СДЭК не ответил или ответил ошибкой."""


class CdekRateLimited(CdekError):
    """429 — упёрлись в лимит запросов. Опрос должен встать на паузу."""


class CdekNotConfigured(CdekError):
    """Не заданы CDEK_CLIENT_ID / CDEK_CLIENT_SECRET."""


# Кэш токена на процесс. Лок нужен, чтобы при одновременных запросах
# не выписать пять токенов вместо одного.
_token: str | None = None
_token_expires_at: datetime | None = None
_token_lock = asyncio.Lock()

# Запас перед истечением: не ждём последней секунды, иначе запрос
# может уйти уже с протухшим токеном.
_TOKEN_LEEWAY_SECONDS = 60


def is_configured() -> bool:
    return bool(settings.cdek_client_id and settings.cdek_client_secret)


def reset_token() -> None:
    """Сбрасывает кэш — например, когда СДЭК ответил 401."""
    global _token, _token_expires_at
    _token = None
    _token_expires_at = None


async def get_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires_at

    if not is_configured():
        raise CdekNotConfigured("Интеграция с СДЭК не настроена (нет CDEK_CLIENT_ID)")

    async with _token_lock:
        now = datetime.now(timezone.utc)
        if _token and _token_expires_at and _token_expires_at > now:
            return _token

        try:
            resp = await client.post(
                f"{settings.cdek_api_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.cdek_client_id,
                    "client_secret": settings.cdek_client_secret,
                },
            )
        except httpx.HTTPError as e:
            raise CdekError(f"Не удалось получить токен СДЭК: {e}")

        if resp.status_code == 429:
            raise CdekRateLimited("СДЭК: слишком много запросов токена")
        if resp.status_code != 200:
            raise CdekError(f"СДЭК вернул {resp.status_code} на запрос токена")

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise CdekError("СДЭК не вернул access_token")

        # expires_in приходит в секундах (обычно 3599)
        ttl = int(data.get("expires_in") or 3600)
        _token = token
        _token_expires_at = now + timedelta(seconds=max(ttl - _TOKEN_LEEWAY_SECONDS, 60))
        return token


async def fetch_order(cdek_number: str, client: httpx.AsyncClient) -> dict | None:
    """Заказ по трек-номеру СДЭК. None — такого заказа у СДЭК нет.

    401 значит, что токен отозвали раньше времени: сбрасываем кэш и пробуем ещё раз.
    """
    for attempt in (1, 2):
        token = await get_token(client)
        try:
            resp = await client.get(
                f"{settings.cdek_api_url}/orders",
                params={"cdek_number": cdek_number},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise CdekError(f"Не удалось запросить заказ у СДЭК: {e}")

        if resp.status_code == 401 and attempt == 1:
            reset_token()
            continue
        if resp.status_code == 429:
            raise CdekRateLimited("СДЭК: слишком много запросов")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise CdekError(f"СДЭК вернул {resp.status_code}")

        entity = resp.json().get("entity")
        # СДЭК отвечает 200 и пустой entity, если номер не его
        return entity or None

    return None


def latest_status(entity: dict) -> dict | None:
    """Текущий статус заказа.

    Сортируем по дате, а не берём первый или последний элемент: порядок
    в ответе СДЭК не документирован (сейчас новые идут первыми, но
    полагаться на это нельзя).
    """
    statuses = [s for s in (entity.get("statuses") or []) if not s.get("deleted")]
    if not statuses:
        return None
    return max(statuses, key=lambda s: s.get("date_time") or "")


def parse_cdek_datetime(value: str | None) -> datetime | None:
    """«2026-07-29T06:14:55+0000» -> datetime с таймзоной."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    # старый формат смещения без двоеточия — питон до 3.11 его не понимал
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
