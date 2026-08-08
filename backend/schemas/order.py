from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class OrderItemIn(BaseModel):
    product_id: int
    size: str | None = Field(default=None, max_length=20)
    # верхняя граница обязательна: иначе qty=999999999 даёт абсурдную сумму
    qty: int = Field(..., ge=1, le=100)


class OrderCreate(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)  # нужен службе доставки
    delivery_method: str = Field(..., min_length=1, max_length=20)  # проверяется по БД
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=20)
    pickup_point: str | None = Field(default=None, max_length=500)
    items: list[OrderItemIn] = Field(..., min_length=1, max_length=50)


class OrderItemResponse(BaseModel):
    id: int
    product_id: int | None
    name: str
    size: str | None
    price: int
    qty: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    number: str
    status: str
    email: str
    full_name: str | None
    phone: str | None
    delivery_method: str
    country: str | None
    city: str | None
    address: str | None
    postal_code: str | None
    pickup_point: str | None
    items_total: int
    delivery_price: int
    total: int
    tracking_number: str | None
    # Подпись статуса от СДЭК («Принят на склад до востребования») —
    # показываем рядом с нашим статусом, она точнее
    cdek_status_name: str | None = None
    cdek_status_at: datetime | None = None
    created_at: datetime
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


class OrderCreated(BaseModel):
    number: str
    payment_url: str


class OrderManualPayment(BaseModel):
    """Отметка об оплате мимо банка. Комментарий — чем подтверждается перевод."""

    note: str | None = Field(default=None, max_length=200)


class PaymentAttemptResponse(BaseModel):
    """Наш вызов Init в Т-Банк. PaymentId ищется в личном кабинете банка."""

    id: int
    payment_id: str | None
    amount: int
    status: str
    error: str | None
    note: str | None
    created_at: datetime
    confirmed_at: datetime | None

    model_config = {"from_attributes": True}


class PaymentNotificationResponse(BaseModel):
    """Входящее уведомление банка. accepted=False + note — почему не засчитали."""

    id: int
    order_number: str | None
    payment_id: str | None
    status: str | None
    amount_kopecks: int | None
    signature_ok: bool
    accepted: bool
    note: str | None
    ip: str | None
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderPaymentsResponse(BaseModel):
    number: str
    status: str
    total: int
    paid_at: datetime | None
    tinkoff_payment_id: str | None  # последняя попытка; полная история — в attempts
    attempts: list[PaymentAttemptResponse]
    notifications: list[PaymentNotificationResponse]


class OrderTrackingUpdate(BaseModel):
    tracking_number: str | None = Field(default=None, max_length=100)


class OrderItemAdminUpdate(BaseModel):
    """Правка позиции заказа админом. Меняем только размер:
    количество и цена влияли бы на уже оплаченную сумму."""

    id: int
    size: str | None = Field(default=None, max_length=20)


class OrderItemAdminAdd(BaseModel):
    """Дозаказ: админ доносит в уже созданный заказ новую позицию.
    Цену можно задать вручную (0 — подарок/замена), иначе берётся текущая цена товара."""

    product_id: int
    size: str | None = Field(default=None, max_length=20)
    qty: int = Field(default=1, ge=1, le=100)
    price: int | None = Field(default=None, ge=0, le=10_000_000)


class OrderAdminUpdate(BaseModel):
    """Правка заказа админом (клиент написал, что ошибся в адресе/размере).
    Суммы существующих позиций не трогаем — они уже оплачены,
    но добавленные позиции меняют итог (доплату админ собирает отдельно)."""

    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    delivery_method: str = Field(..., min_length=1, max_length=20)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=20)
    pickup_point: str | None = Field(default=None, max_length=500)
    items: list[OrderItemAdminUpdate] = Field(default_factory=list, max_length=50)
    new_items: list[OrderItemAdminAdd] = Field(default_factory=list, max_length=50)
