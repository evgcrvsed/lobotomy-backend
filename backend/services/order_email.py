"""Письмо покупателю после оплаты заказа.

Главное в письме — номер заказа и ссылка на него. Для гостя это единственная
запись о заказе: профиля у него нет, а вкладку с чеком он может закрыть.
"""

from html import escape

from backend.config import settings
from backend.models import Order
from backend.services.email_service import send_email

# Инлайновые стили: почтовые клиенты вырезают <style> и внешние таблицы стилей
_TEXT = "font-family:Helvetica,Arial,sans-serif;color:#111111"
_MUTED = "color:#888888;font-size:13px;line-height:1.6"


def _rub(value: int) -> str:
    """5500 -> «5 500 ₽».

    Пробелы неразрывные — как и в formatPrice на сайте: иначе почтовый клиент
    может разорвать сумму по строкам. Записаны escape-последовательностью,
    чтобы в исходнике их было видно.
    """
    return f"{value:,}".replace(",", " ") + " ₽"


def build_html(order: Order, delivery_label: str) -> str:
    order_url = f"{settings.site_url}/order/{order.number}"

    rows = "".join(
        "<tr>"
        f'<td style="padding:8px 0;{_TEXT};font-size:14px">'
        f"{escape(item.name)}"
        + (f' <span style="color:#888">· {escape(item.size)}</span>' if item.size else "")
        + f' <span style="color:#888">× {item.qty}</span>'
        "</td>"
        f'<td style="padding:8px 0;text-align:right;{_TEXT};font-size:14px;white-space:nowrap">'
        f"{_rub(item.price * item.qty)}</td>"
        "</tr>"
        for item in order.items
    )

    address = ", ".join(
        escape(part)
        for part in (order.country, order.city, order.address, order.postal_code, order.pickup_point)
        if part
    )

    return f"""
<div style="{_TEXT};max-width:520px;margin:0 auto;padding:8px">
  <p style="font-size:15px;margin:0 0 18px">Спасибо за заказ в <strong>LOBOTOMY</strong>. Оплата прошла.</p>

  <div style="border:1px solid #e5e5e5;border-radius:8px;padding:18px 20px;margin-bottom:20px">
    <div style="{_MUTED};text-transform:uppercase;letter-spacing:0.06em;font-size:11px">Номер заказа</div>
    <div style="font-size:26px;font-weight:700;letter-spacing:2px;margin-top:4px">{order.number}</div>
    <p style="{_MUTED};margin:12px 0 0">
      Сохраните этот номер — по нему можно открыть заказ и посмотреть трек-номер.
    </p>
  </div>

  <a href="{order_url}"
     style="display:inline-block;padding:13px 26px;background:#111111;color:#ffffff;
            text-decoration:none;border-radius:8px;font-size:15px">Открыть заказ</a>

  <table style="width:100%;border-collapse:collapse;margin-top:28px">
    <tr><td colspan="2" style="{_MUTED};text-transform:uppercase;letter-spacing:0.06em;font-size:11px;
        padding-bottom:6px;border-bottom:1px solid #e5e5e5">Состав</td></tr>
    {rows}
    <tr><td style="padding-top:12px;border-top:1px solid #e5e5e5;{_TEXT};font-size:14px">
        Доставка — {escape(delivery_label)}</td>
      <td style="padding-top:12px;border-top:1px solid #e5e5e5;text-align:right;{_TEXT};font-size:14px">
        {_rub(order.delivery_price)}</td></tr>
    <tr><td style="padding-top:8px;{_TEXT};font-size:16px;font-weight:700">Итого</td>
      <td style="padding-top:8px;text-align:right;{_TEXT};font-size:16px;font-weight:700">
        {_rub(order.total)}</td></tr>
  </table>

  {f'<p style="{_MUTED};margin-top:22px">Куда везём: {address}</p>' if address else ""}

  <p style="{_MUTED};margin-top:22px">
    Как только заказ отправится, у него появится трек-номер — он виден на странице заказа.
  </p>
  <p style="{_MUTED};margin-top:18px">
    <a href="{settings.site_url}" style="color:#888888">{settings.site_url}</a>
  </p>
</div>
""".strip()


async def send_order_confirmation(order: Order, delivery_label: str) -> None:
    await send_email(
        order.email,
        f"Заказ {order.number} оплачен — LOBOTOMY",
        build_html(order, delivery_label),
    )
