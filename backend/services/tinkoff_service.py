import hashlib

import httpx

from backend.config import settings


class TinkoffError(Exception):
    pass


def _stringify(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def make_token(params: dict) -> str:
    """Подпись запроса/уведомления по правилам Т-Банка:
    берём только корневые скалярные поля (без вложенных объектов и без Token),
    добавляем Password, сортируем по ключу, склеиваем значения, считаем SHA-256.
    """
    data = {
        k: v
        for k, v in params.items()
        if k != "Token" and not isinstance(v, (dict, list)) and v is not None
    }
    data["Password"] = settings.tinkoff_password
    concatenated = "".join(_stringify(data[k]) for k in sorted(data))
    return hashlib.sha256(concatenated.encode("utf-8")).hexdigest()


def verify_notification(payload: dict) -> bool:
    """Проверяет подпись уведомления от Т-Банка."""
    received = payload.get("Token", "")
    return bool(received) and make_token(payload) == received


async def init_payment(*, order_number: str, amount_rub: int, email: str, description: str) -> dict:
    """Создаёт платёж (метод Init) и возвращает ответ Т-Банка с PaymentURL и PaymentId."""
    if not settings.tinkoff_terminal_key:
        raise TinkoffError("Оплата не настроена (нет TINKOFF_TERMINAL_KEY)")

    payload = {
        "TerminalKey": settings.tinkoff_terminal_key,
        "Amount": amount_rub * 100,  # Т-Банк принимает сумму в копейках
        "OrderId": order_number,
        "Description": description,
        "NotificationURL": f"{settings.site_url}/api/payments/tinkoff/webhook",
        "SuccessURL": f"{settings.site_url}/checkout/success",
        "FailURL": f"{settings.site_url}/checkout/fail",
    }
    payload["Token"] = make_token(payload)
    payload["DATA"] = {"Email": email}  # объект — в подпись не входит

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{settings.tinkoff_api_url}/Init", json=payload)
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

    if not data.get("Success"):
        raise TinkoffError(data.get("Message") or data.get("Details") or "Т-Банк отклонил платёж")
    return data
