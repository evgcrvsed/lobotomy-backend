from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User
from backend.schemas.order import (
    OrderAdminUpdate,
    OrderCreate,
    OrderCreated,
    OrderResponse,
    OrderTrackingUpdate,
)
from backend.services.auth_service import client_ip, get_current_admin, get_current_user, get_optional_user
from backend.services.cdek_service import CdekError
from backend.services.cdek_sync import sync_order
from backend.services.email_service import EmailNotConfiguredError, EmailSendError
from backend.services.order_service import OrderError, OrderService
from backend.services.tinkoff_service import TinkoffError, init_payment, verify_notification

router = APIRouter(prefix="/api", tags=["orders"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
admin_only = [Depends(get_current_admin)]


@router.post("/orders", response_model=OrderCreated, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    request: Request,
    db: DbDep,
    user: Annotated[User | None, Depends(get_optional_user)],
):
    service = OrderService(db)
    try:
        order = await service.create(data, user, ip=client_ip(request))
    except OrderError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        payment = await init_payment(
            order_number=order.number,
            amount_rub=order.total,
            email=order.email,
            description=f"Заказ {order.number}",
        )
    except TinkoffError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    order.tinkoff_payment_id = str(payment.get("PaymentId"))
    await db.commit()
    return {"number": order.number, "payment_url": payment["PaymentURL"]}


@router.post("/orders/{number}/pay", response_model=OrderCreated)
async def resume_payment(number: str, db: DbDep):
    service = OrderService(db)
    order = await service.get_by_number(number)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")
    if order.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Заказ отменён — неоплаченные заказы живут час. Оформите новый",
        )
    if order.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заказ уже оплачен")

    try:
        payment = await init_payment(
            order_number=order.number,
            amount_rub=order.total,
            email=order.email,
            description=f"Заказ {order.number}",
        )
    except TinkoffError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    order.tinkoff_payment_id = str(payment.get("PaymentId"))
    await db.commit()
    return {"number": order.number, "payment_url": payment["PaymentURL"]}


@router.post("/payments/tinkoff/webhook")
async def tinkoff_webhook(request: Request, db: DbDep):
    payload = await request.json()
    if not verify_notification(payload):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad signature")

    # CONFIRMED — оплата прошла (одностадийная схема)
    if payload.get("Status") == "CONFIRMED":
        amount = payload.get("Amount")
        number = str(payload.get("OrderId"))
        service = OrderService(db)
        ok = await service.mark_paid(
            number=number,
            payment_id=str(payload.get("PaymentId")) if payload.get("PaymentId") else None,
            amount_kopecks=int(amount) if amount is not None else None,
        )
        if not ok:
            # заказ не найден или сумма разошлась — в логи, разбирать вручную
            print(f"[webhook] не удалось подтвердить заказ {number}, сумма {amount}")
        else:
            # Письмо с номером заказа. Ошибка почты не должна валить обработку:
            # иначе Т-Банк не увидит "OK" и будет слать уведомление снова.
            try:
                order = await service.get_by_number(number)
                if order is not None and await service.send_confirmation(order):
                    print(f"[webhook] письмо о заказе {number} отправлено на {order.email}")
            except (EmailNotConfiguredError, EmailSendError) as e:
                print(f"[webhook] заказ {number} оплачен, но письмо не ушло: {e}")
    # Т-Банк ждёт именно тело "OK", иначе будет повторять уведомление
    return PlainTextResponse("OK")


@router.get("/orders/track/{number}", response_model=OrderResponse)
async def track_order(number: str, db: DbDep):
    order = await OrderService(db).get_by_number(number)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")
    # привязанные к аккаунту заказы через публичный трек не показываем
    if order.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Этот заказ привязан к аккаунту — войдите, чтобы посмотреть его в профиле",
        )
    return order


@router.get("/orders/my", response_model=list[OrderResponse])
async def my_orders(db: DbDep, user: Annotated[User, Depends(get_current_user)]):
    return await OrderService(db).list_for_user(user)


@router.get("/orders", response_model=list[OrderResponse], dependencies=admin_only)
async def all_orders(db: DbDep):
    """Все заказы — для админской страницы."""
    return await OrderService(db).list_all()


@router.patch("/orders/{number}", response_model=OrderResponse, dependencies=admin_only)
async def admin_update_order(number: str, data: OrderAdminUpdate, db: DbDep):
    """Правка заказа админом — если покупатель ошибся в адресе или размере."""
    try:
        order = await OrderService(db).admin_update(number, data)
    except OrderError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")
    return order


@router.patch("/orders/{number}/tracking", response_model=OrderResponse, dependencies=admin_only)
async def set_tracking(number: str, data: OrderTrackingUpdate, db: DbDep):
    order = await OrderService(db).set_tracking(number, (data.tracking_number or "").strip())
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")
    return order


@router.post("/orders/{number}/cdek-sync", response_model=OrderResponse, dependencies=admin_only)
async def sync_cdek(number: str, db: DbDep):
    """Спросить у СДЭК статус прямо сейчас, не дожидаясь фонового опроса."""
    service = OrderService(db)
    order = await service.get_by_number(number)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")
    if not order.tracking_number:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="У заказа нет трек-номера")

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            await sync_order(order, client)
    except CdekError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    await db.commit()
    await db.refresh(order, attribute_names=["items"])
    return order


@router.get("/orders/{number}", response_model=OrderResponse)
async def get_order(
    number: str,
    db: DbDep,
    user: Annotated[User | None, Depends(get_optional_user)],
):
    order = await OrderService(db).get_by_number(number)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заказ не найден")
    # чужой привязанный заказ не отдаём; гостевой (user_id пустой) — публичный по номеру
    if order.user_id is not None and (user is None or user.id != order.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к этому заказу")
    return order
