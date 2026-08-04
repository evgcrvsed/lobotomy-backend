import hashlib

import httpx

from backend.config import settings
from backend.models import Order


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


def _build_receipt(order: Order) -> dict:
    """Фискальный чек (54-ФЗ). Боевой терминал отклоняет Init без него —
    ErrorCode 309 "expected.receipt", проверено на реальном терминале.

    Позиции строим из order.items + доставка отдельной строкой — так сумма
    чека всегда совпадает с Amount платежа копейка в копейку, это Т-Банк
    тоже проверяет.
    """
    items = [
        {
            "Name": item.name[:128],  # ограничение Т-Банка на длину названия
            "Price": item.price * 100,
            "Quantity": item.qty,
            "Amount": item.price * item.qty * 100,
            "Tax": settings.tinkoff_receipt_vat,
        }
        for item in order.items
    ]
    if order.delivery_price:
        items.append({
            "Name": "Доставка",
            "Price": order.delivery_price * 100,
            "Quantity": 1,
            "Amount": order.delivery_price * 100,
            "Tax": settings.tinkoff_receipt_vat,
        })

    return {
        "Email": order.email,
        "Taxation": settings.tinkoff_receipt_taxation,
        "Items": items,
    }


async def init_payment(*, order: Order, description: str) -> dict:
    """Создаёт платёж (метод Init) и возвращает ответ Т-Банка с PaymentURL и PaymentId."""
    if not settings.tinkoff_terminal_key:
        raise TinkoffError("Оплата не настроена (нет TINKOFF_TERMINAL_KEY)")

    payload = {
        "TerminalKey": settings.tinkoff_terminal_key,
        "Amount": order.total * 100,  # Т-Банк принимает сумму в копейках
        "OrderId": order.number,
        "Description": description,
        "NotificationURL": f"{settings.site_url}/api/payments/tinkoff/webhook",
        # Номер заказа — в пути, а не в query: Т-Банк дописывает к этим адресам
        # свои параметры (?Success=...), и наш ?order=... с ними бы столкнулся.
        # Без номера гость после оплаты не смог бы найти свой заказ.
        "SuccessURL": f"{settings.site_url}/checkout/success/{order.number}",
        "FailURL": f"{settings.site_url}/checkout/fail/{order.number}",
    }
    payload["Token"] = make_token(payload)
    payload["DATA"] = {"Email": order.email}  # объект — в подпись не входит
    payload["Receipt"] = _build_receipt(order)  # тоже объект — в подпись не входит

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(f"{settings.tinkoff_api_url}/Init", json=payload)
    except httpx.HTTPError as e:
        # Сеть/таймаут/TLS — без этого падало необработанным исключением (500)
        # вместо понятной ошибки покупателю
        raise TinkoffError(f"Т-Банк не ответил: {e}")

    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

    if not data.get("Success"):
        message = data.get("Message") or data.get("Details") or "Т-Банк отклонил платёж"
        # ErrorCode и Details — самое полезное для разбора в логах (например,
        # 309 "expected.receipt" — сразу видно, что дело в чеке, а не гадать)
        print(f"[tinkoff] Init отклонён: код {data.get('ErrorCode')}, {message}, детали: {data.get('Details')}")
        raise TinkoffError(message)
    return data
