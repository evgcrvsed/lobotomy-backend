import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.models import DeliveryMethod, Order, OrderItem, Product, User
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

    async def create(self, data: OrderCreate, user: User | None, ip: str | None = None) -> Order:
        # Антиспам: с одного IP нельзя лепить заказы пачками
        # (каждый заказ — это ещё и запрос на создание платежа в Т-Банк)
        if ip:
            recent = await self.db.execute(
                select(func.count())
                .select_from(Order)
                .where(Order.ip == ip, Order.created_at > datetime.now(timezone.utc) - timedelta(minutes=10))
            )
            if recent.scalar_one() >= settings.order_ip_limit_10min:
                raise OrderError("Слишком много заказов подряд. Попробуйте через несколько минут")

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

        # Цена доставки — из БД (её меняет админ), а не из клиента и не из кода
        method = await self.db.execute(
            select(DeliveryMethod).where(DeliveryMethod.code == data.delivery_method)
        )
        delivery = method.scalar_one_or_none()
        if delivery is None:
            raise OrderError(f"Способ доставки «{data.delivery_method}» недоступен")
        delivery_price = delivery.price

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
            ip=ip,
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

    async def mark_paid(self, number: str, payment_id: str | None, amount_kopecks: int | None = None) -> bool:
        """Помечает заказ оплаченным. Возвращает False, если заказа нет
        или пришедшая сумма не совпала с суммой заказа."""
        order = await self.get_by_number(number)
        if order is None:
            return False
        # сверяем сумму: она пришла подписанной от банка, но лучше убедиться,
        # что оплатили именно столько, сколько стоит заказ
        if amount_kopecks is not None and amount_kopecks != order.total * 100:
            return False
        if order.status in ("paid", "shipped"):  # повторное уведомление — ничего не меняем
            return True
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        if payment_id:
            order.tinkoff_payment_id = payment_id
        await self.db.commit()
        return True

    async def list_all(self) -> list[Order]:
        """Все заказы — для админки (включая отменённые и неоплаченные)."""
        await self._expire_stale_pending()
        result = await self.db.execute(
            select(Order).options(selectinload(Order.items)).order_by(Order.created_at.desc())
        )
        return list(result.scalars())

    async def set_tracking(self, number: str, tracking: str | None) -> Order | None:
        order = await self.get_by_number(number)
        if order is None:
            return None
        order.tracking_number = tracking or None
        # появился трек у оплаченного заказа — считаем его отправленным
        if order.tracking_number and order.status == "paid":
            order.status = "shipped"
        elif not order.tracking_number and order.status == "shipped":
            order.status = "paid"
        await self.db.commit()
        await self.db.refresh(order, attribute_names=["items"])
        return order

    async def admin_update(self, number: str, data) -> Order | None:
        """Правка заказа админом: контакты, адрес, способ доставки, размеры позиций.
        Суммы намеренно не пересчитываем — заказ уже оплачен, деньги прошли."""
        order = await self.get_by_number(number)
        if order is None:
            return None

        method = await self.db.execute(
            select(DeliveryMethod).where(DeliveryMethod.code == data.delivery_method)
        )
        if method.scalar_one_or_none() is None:
            raise OrderError(f"Способ доставки «{data.delivery_method}» недоступен")

        order.email = str(data.email).lower()
        order.full_name = data.full_name
        order.phone = data.phone
        order.delivery_method = data.delivery_method
        order.country = data.country
        order.city = data.city
        order.address = data.address
        order.postal_code = data.postal_code
        order.pickup_point = data.pickup_point

        sizes = {i.id: i.size for i in data.items}
        for item in order.items:
            if item.id in sizes:
                item.size = sizes[item.id]

        await self.db.commit()
        await self.db.refresh(order, attribute_names=["items"])
        return order

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
