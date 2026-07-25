import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.models import Order, OrderItem, Product, User
from backend.schemas.order import OrderCreate


class OrderError(Exception):
    pass


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _unique_number(self) -> str:
        while True:
            number = secrets.token_hex(5).upper()  # напр. 7F3A9C2B4E — неугадываемый, без приставки
            exists = await self.db.execute(select(Order.id).where(Order.number == number))
            if exists.first() is None:
                return number

    async def create(self, data: OrderCreate, user: User | None) -> Order:
        # Собираем товары и считаем сумму ТОЛЬКО по ценам из БД — клиенту не доверяем
        product_ids = {i.product_id for i in data.items}
        result = await self.db.execute(select(Product).where(Product.id.in_(product_ids)))
        products = {p.id: p for p in result.scalars()}

        items: list[OrderItem] = []
        items_total = 0
        for line in data.items:
            product = products.get(line.product_id)
            if product is None:
                raise OrderError(f"Товар id={line.product_id} не найден")
            items_total += product.price * line.qty
            items.append(OrderItem(
                product_id=product.id,
                name=product.name,
                size=line.size,
                price=product.price,
                qty=line.qty,
            ))

        delivery_price = settings.delivery_prices.get(data.delivery_method, 0)

        order = Order(
            number=await self._unique_number(),
            user_id=user.id if user else None,
            email=str(data.email).lower(),
            full_name=data.full_name,
            phone=data.phone,
            delivery_method=data.delivery_method,
            country=data.country,
            city=data.city,
            address=data.address,
            postal_code=data.postal_code,
            pickup_point=data.pickup_point,
            items_total=items_total,
            delivery_price=delivery_price,
            total=items_total + delivery_price,
            status="pending",
            items=items,
        )
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order, attribute_names=["items"])
        return order

    async def _expire_stale_pending(self) -> None:
        """Брошенные (неоплаченные) заказы старше TTL помечаем отменёнными."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.pending_order_ttl_minutes)
        await self.db.execute(
            update(Order)
            .where(Order.status == "pending", Order.created_at < cutoff)
            .values(status="cancelled")
        )
        await self.db.commit()

    async def get_by_number(self, number: str) -> Order | None:
        await self._expire_stale_pending()
        result = await self.db.execute(
            select(Order).where(Order.number == number).options(selectinload(Order.items))
        )
        return result.scalar_one_or_none()

    async def mark_paid(self, number: str, payment_id: str | None) -> None:
        order = await self.get_by_number(number)
        if order is None or order.status == "paid":
            return
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        if payment_id:
            order.tinkoff_payment_id = payment_id
        await self.db.commit()

    async def list_for_user(self, user: User) -> list[Order]:
        await self._expire_stale_pending()
        result = await self.db.execute(
            select(Order)
            .where(Order.user_id == user.id, Order.status != "cancelled")  # брошенные не показываем
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars())

    async def claim_guest_orders(self, user: User) -> None:
        """При входе привязываем к пользователю все гостевые заказы с его почтой."""
        if not user.email:
            return
        await self.db.execute(
            update(Order)
            .where(Order.user_id.is_(None), Order.email == user.email.lower())
            .values(user_id=user.id)
        )
        await self.db.commit()
