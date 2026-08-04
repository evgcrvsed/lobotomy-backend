"""Уведомление админу в Telegram о новом оплаченном заказе."""

from html import escape

from backend.config import settings
from backend.models import DeliveryMethod, Order
from backend.services.telegram_service import notify


def _rub(value: int) -> str:
    """5500 -> «5 500 ₽». Пробелы обычные, в отличие от письма: в телеграме
    неразрывные не нужны, а копипастить сумму из чата удобнее без них."""
    return f"{value:,}".replace(",", " ") + " ₽"


def build_text(order: Order, delivery: DeliveryMethod | None) -> str:
    """Короткая сводка по заказу. HTML — телеграмный, из тегов только <b>."""
    delivery_label = delivery.label if delivery else order.delivery_method

    items = "\n".join(
        f"• {escape(item.name)}"
        + (f" ({escape(item.size)})" if item.size else "")
        + f" × {item.qty} — {_rub(item.price * item.qty)}"
        for item in order.items
    )
    address = ", ".join(
        escape(part)
        for part in (order.country, order.city, order.address, order.postal_code, order.pickup_point)
        if part
    )

    lines = [
        f"💰 <b>Оплачен заказ {escape(order.number)}</b>",
        "",
        items,
        "",
        f"Доставка: {escape(delivery_label)} — {_rub(order.delivery_price)}",
        f"<b>Итого: {_rub(order.total)}</b>",
        "",
        f"Покупатель: {escape(order.full_name or '—')}",
        f"Почта: {escape(order.email)}",
    ]
    if order.phone:
        lines.append(f"Телефон: {escape(order.phone)}")
    if address:
        lines.append(f"Куда: {address}")
    lines.append("")
    lines.append(f"{settings.site_url}/admin/orders/{order.number}")

    return "\n".join(lines)


def notify_paid_order(order: Order, delivery: DeliveryMethod | None) -> None:
    """Шлём в фоне — вебхук Т-Банка не должен ждать телеграм."""
    notify(build_text(order, delivery))
