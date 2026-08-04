"""Письмо покупателю после оплаты заказа.

Дублирует всё, что покупатель видел при оформлении: номер, состав, свои данные,
адрес доставки и суммы. Для гостя это единственная запись о заказе — профиля у
него нет, а вкладку с чеком он может закрыть.
"""

from datetime import timedelta, timezone
from html import escape

from backend.config import settings
from backend.models import DeliveryMethod, Order
from backend.services.email_service import send_email

# Инлайновые стили: почтовые клиенты вырезают <style> и внешние таблицы стилей
_TEXT = "font-family:Helvetica,Arial,sans-serif;color:#111111"
_MUTED = "color:#888888;font-size:13px;line-height:1.6"
_LABEL = (
    "color:#888888;font-size:11px;text-transform:uppercase;"
    "letter-spacing:0.06em;padding:7px 12px 7px 0;vertical-align:top"
)
_VALUE = "font-size:14px;color:#111111;padding:7px 0;vertical-align:top"
_SECTION = (
    "color:#888888;font-size:11px;text-transform:uppercase;letter-spacing:0.06em;"
    "padding-bottom:6px;border-bottom:1px solid #e5e5e5"
)

# Заказы принимаются по московскому времени — его и показываем, чтобы дата
# не разъезжалась с той, что видит владелец магазина в админке.
MOSCOW = timezone(timedelta(hours=3))


def _rub(value: int) -> str:
    """5500 -> «5 500 ₽».

    Пробелы неразрывные — как и в formatPrice на сайте: иначе почтовый клиент
    может разорвать сумму по строкам.
    """
    return f"{value:,}".replace(",", " ") + " ₽"


def _rows(pairs: list[tuple[str, str | None]]) -> str:
    """Строки «подпись — значение». Пустые поля пропускаем, чтобы не было прочерков."""
    return "".join(
        f'<tr><td style="{_LABEL}">{escape(label)}</td>'
        f'<td style="{_VALUE}">{escape(str(value))}</td></tr>'
        for label, value in pairs
        if value
    )


def build_html(order: Order, delivery: DeliveryMethod | None) -> str:
    # Страница подтверждения заказа — та же, куда Т-Банк возвращает после оплаты
    order_url = f"{settings.site_url}/checkout/success/{order.number}"

    delivery_label = delivery.label if delivery else order.delivery_method
    index_label = delivery.index_label if delivery else "Индекс"
    point_label = delivery.point_label if delivery else "Адрес"

    items = "".join(
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

    created = order.created_at.astimezone(MOSCOW).strftime("%d.%m.%Y, %H:%M") if order.created_at else None

    buyer = _rows([
        ("ФИО", order.full_name),
        ("Почта", order.email),
        ("Телефон", order.phone),
    ])
    shipping = _rows([
        ("Способ", f"{delivery_label} — {_rub(order.delivery_price)}"),
        ("Страна", order.country),
        ("Город", order.city),
        ("Адрес", order.address),
        (index_label, order.postal_code),
        (point_label, order.pickup_point),
    ])

    return f"""
<div style="{_TEXT};max-width:520px;margin:0 auto;padding:8px">
  <p style="font-size:15px;margin:0 0 18px">Спасибо за заказ в <strong>LOBOTOMY</strong>. Оплата прошла.</p>

  <div style="border:1px solid #e5e5e5;border-radius:8px;padding:18px 20px;margin-bottom:20px">
    <div style="{_MUTED};text-transform:uppercase;letter-spacing:0.06em;font-size:11px">Номер заказа</div>
    <div style="font-size:26px;font-weight:700;letter-spacing:2px;margin-top:4px">{order.number}</div>
    {f'<div style="{_MUTED};margin-top:2px">от {created} МСК</div>' if created else ""}
    <p style="{_MUTED};margin:12px 0 0">
      Сохраните этот номер — по нему можно открыть заказ и посмотреть трек-номер.
    </p>
  </div>

  <a href="{order_url}"
     style="display:inline-block;padding:13px 26px;background:#111111;color:#ffffff;
            text-decoration:none;border-radius:8px;font-size:15px">Открыть заказ</a>

  <table style="width:100%;border-collapse:collapse;margin-top:28px">
    <tr><td colspan="2" style="{_SECTION}">Состав</td></tr>
    {items}
    <tr><td style="padding-top:12px;border-top:1px solid #e5e5e5;{_TEXT};font-size:14px">
        Доставка — {escape(delivery_label)}</td>
      <td style="padding-top:12px;border-top:1px solid #e5e5e5;text-align:right;{_TEXT};font-size:14px">
        {_rub(order.delivery_price)}</td></tr>
    <tr><td style="padding-top:8px;{_TEXT};font-size:16px;font-weight:700">Итого</td>
      <td style="padding-top:8px;text-align:right;{_TEXT};font-size:16px;font-weight:700">
        {_rub(order.total)}</td></tr>
  </table>

  <table style="width:100%;border-collapse:collapse;margin-top:28px">
    <tr><td colspan="2" style="{_SECTION}">Покупатель</td></tr>
    {buyer}
  </table>

  <table style="width:100%;border-collapse:collapse;margin-top:24px">
    <tr><td colspan="2" style="{_SECTION}">Доставка</td></tr>
    {shipping}
  </table>

  <p style="{_MUTED};margin-top:26px">
    Как только заказ отправится, у него появится трек-номер — он виден на странице заказа.
    Если в данных ошибка, ответьте на это письмо или напишите нам в соцсетях.
  </p>
  <p style="{_MUTED};margin-top:18px">
    <a href="{settings.site_url}" style="color:#888888">{settings.site_url}</a>
  </p>
</div>
""".strip()


async def send_order_confirmation(order: Order, delivery: DeliveryMethod | None) -> None:
    await send_email(
        to=order.email,
        subject=f"Заказ {order.number} оплачен — LOBOTOMY",
        html=build_html(order, delivery),
        from_address=f'"LOBOTOMY" <{settings.email_from_orders}>',
    )
