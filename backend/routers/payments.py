from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User
from backend.schemas.order import OrderCreate, OrderCreated, OrderResponse
from backend.services.auth_service import get_current_user, get_optional_user
from backend.services.order_service import OrderError, OrderService
from backend.services.tinkoff_service import TinkoffError, init_payment, verify_notification

router = APIRouter(prefix="/api", tags=["orders"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/orders", response_model=OrderCreated, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    db: DbDep,
    user: Annotated[User | None, Depends(get_optional_user)],
):
    service = OrderService(db)
    try:
        order = await service.create(data, user)
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


@router.post("/payments/tinkoff/webhook")
async def tinkoff_webhook(request: Request, db: DbDep):
    payload = await request.json()
    if not verify_notification(payload):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad signature")

    # CONFIRMED — оплата прошла (одностадийная схема)
    if payload.get("Status") == "CONFIRMED":
        await OrderService(db).mark_paid(
            number=str(payload.get("OrderId")),
            payment_id=str(payload.get("PaymentId")) if payload.get("PaymentId") else None,
        )
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
