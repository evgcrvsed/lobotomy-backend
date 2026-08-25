import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.models import DeliveryMethod, Order, OrderItem, Product, User
from backend.schemas.order import OrderCreate
from backend.services.order_email import send_order_confirmation


class OrderError(Exception):
    pass


# Статусы, которые ещё требуют внимания админа. Вручённые и отменённые —
# архив: в списке их нет, но поиск их находит
ACTIVE_STATUSES = ("pending", "paid", "shipped", "ready")
SEARCH_LIMIT = 100
# Короткий огрызок цифр («7») совпал бы с половиной телефонов — не ищем по нему
MIN_PHONE_DIGITS = 3


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

        # У авторизованного почта берётся из профиля, а не из формы: она подтверждена
        # входом. Иначе можно было бы оформить заказ на чужой адрес.
        email = (user.email or str(data.email)).lower() if user else str(data.email).lower()

        order = Order(
            number=await self._unique_number(),
            user_id=user.id if user else None,
            email=email,
            full_name=data.full_name,
            phone=data.phone or (user.phone if user else None),
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

        # Данные доставки запоминаем в профиле — чтобы в следующий раз подставились.
        # Почту НЕ трогаем: она подтверждена входом и менять её через заказ нельзя.
        if user is not None:
            user.full_name = data.full_name or user.full_name
            user.phone = data.phone or user.phone
            user.country = data.country or user.country
            user.city = data.city or user.city
            user.address = data.address or user.address
            user.postal_code = data.postal_code or user.postal_code
            user.pickup_point = data.pickup_point or user.pickup_point

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
        # Повторное уведомление — ничего не меняем. Проверять сумму тут нельзя:
        # админ мог дозаказать позицию, и total уже отличается от оплаченного.
        if order.status in ("paid", "shipped"):
            return True
        # сумма пришла подписанной от банка, но лучше убедиться
        if amount_kopecks is not None and amount_kopecks != order.total * 100:
            return False
        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        if payment_id:
            order.tinkoff_payment_id = payment_id
        await self.db.commit()
        return True

    async def send_confirmation(self, order: Order) -> bool:
        """Письмо покупателю с номером заказа. Возвращает True, если отправили.

        Отметка о письме в БД, а не просто «раз оплатили — шлём»: Т-Банк
        повторяет уведомление, и без отметки покупатель получил бы несколько
        одинаковых писем. Если письмо не ушло, отметка не ставится — повторное
        уведомление попробует ещё раз.
        """
        if order.confirmation_sent_at is not None:
            return False

        method = await self.db.execute(
            select(DeliveryMethod).where(DeliveryMethod.code == order.delivery_method)
        )
        # способ целиком: из него берутся и название, и подписи полей адреса
        await send_order_confirmation(order, method.scalar_one_or_none())
        order.confirmation_sent_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    async def list_active(self) -> list[Order]:
        """Заказы, с которыми ещё есть работа.

        Вручённые и отменённые в списке админки не нужны — они только мешают
        видеть текущие. Найти их можно поиском: search() смотрит по всем статусам.
        """
        await self._expire_stale_pending()
        result = await self.db.execute(
            select(Order)
            .where(Order.status.in_(ACTIVE_STATUSES))
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars())

    async def search(self, query: str) -> list[Order]:
        """Поиск по номеру, ФИО, почте и телефону — по всем заказам, включая архивные."""
        await self._expire_stale_pending()
        text = query.strip()
        if not text:
            return []

        like = f"%{text}%"
        conditions = [
            Order.number.ilike(like),
            Order.full_name.ilike(like),
            Order.email.ilike(like),
            Order.phone.ilike(like),
        ]

        # Телефон в базе записан как его ввёл покупатель («+7 900 000-00-00»),
        # а ищут обычно подряд идущими цифрами — сравниваем и по ним тоже
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= MIN_PHONE_DIGITS:
            conditions.append(
                func.regexp_replace(Order.phone, r"\D", "", "g").like(f"%{digits}%")
            )

        result = await self.db.execute(
            select(Order)
            .where(or_(*conditions))
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(SEARCH_LIMIT)
        )
        return list(result.scalars())

    async def mark_paid_manually(self, number: str) -> Order | None:
        """Оплата пришла мимо банка (перевод на карту) — админ подтверждает её сам.

        Отменённый заказ тоже поднимаем: его отменил счётчик неоплаченных, а деньги
        всё-таки пришли. Сумму не сверяем — банк её не присылал, за неё отвечает админ.
        """
        order = await self.get_by_number(number)
        if order is None:
            return None
        if order.status not in ("pending", "cancelled"):
            raise OrderError("Заказ уже оплачен")

        order.status = "paid"
        order.paid_at = datetime.now(timezone.utc)
        await self.db.commit()
        return order

    async def delete(self, number: str) -> bool:
        """Удаляет заказ вместе с позициями и всем журналом оплаты. Безвозвратно.

        Связи грузим сразу: удаление тянет за собой каскад, а ленивая подгрузка
        внутри async-сессии на этом и падает.
        """
        result = await self.db.execute(
            select(Order)
            .where(Order.number == number)
            .options(
                selectinload(Order.items),
                selectinload(Order.payment_attempts),
                selectinload(Order.payment_notifications),
            )
        )
        order = result.scalar_one_or_none()
        if order is None:
            return False

        await self.db.delete(order)
        await self.db.commit()
        return True

    async def set_tracking(self, number: str, tracking: str | None) -> Order | None:
        order = await self.get_by_number(number)
        if order is None:
            return None
        changed = order.tracking_number != (tracking or None)
        order.tracking_number = tracking or None
        if order.tracking_number and order.status == "paid":
            order.status = "shipped"
        elif not order.tracking_number:
            # трек убрали — статусы СДЭК больше ни о чём не говорят
            if order.status in ("shipped", "ready", "delivered"):
                order.status = "paid"
            order.cdek_status_code = None
            order.cdek_status_name = None
            order.cdek_status_at = None
        if changed:
            # номер новый — пусть ближайший проход СДЭК проверит его сразу,
            # не дожидаясь окна перепроверки
            order.cdek_checked_at = None
        await self.db.commit()
        await self.db.refresh(order, attribute_names=["items"])
        return order

    async def admin_update(self, number: str, data) -> Order | None:
        """Правка заказа админом: контакты, адрес, способ доставки, размеры позиций
        и дозаказ новых позиций.

        Цены и количества уже оплаченных позиций не трогаем — деньги прошли.
        А вот добавленные позиции меняют items_total и total: доплату админ
        собирает отдельно, заказ лишь фиксирует, что именно клиент получит."""
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

        new_items = getattr(data, "new_items", None) or []
        if new_items:
            result = await self.db.execute(
                select(Product).where(Product.id.in_({i.product_id for i in new_items}))
            )
            products = {p.id: p for p in result.scalars()}
            for line in new_items:
                product = products.get(line.product_id)
                if product is None:
                    raise OrderError(f"Товар id={line.product_id} не найден")
                order.items.append(OrderItem(
                    product_id=product.id,
                    name=product.name,
                    size=line.size,
                    # цену админ может задать вручную (0 — подарок или замена),
                    # иначе берём текущую цену товара
                    price=product.price if line.price is None else line.price,
                    qty=line.qty,
                ))
            order.items_total = sum(i.price * i.qty for i in order.items)
            order.total = order.items_total + order.delivery_price

        await self.db.commit()
        await self.db.refresh(order, attribute_names=["items"])
        return order

    async def remove_item(self, number: str, item_id: int) -> Order | None:
        """Убирает одну позицию из заказа и пересчитывает суммы.

        Отдельным действием, а не через admin_update: там список позиций служит
        для правки размеров, и делать его ещё и «кого нет — того удалить» опасно —
        любая ошибка на фронтенде молча вынесла бы состав заказа.

        Последнюю позицию убрать нельзя: заказ без товаров — это не заказ,
        такой надо удалять целиком (есть отдельная кнопка).
        """
        order = await self.get_by_number(number)
        if order is None:
            return None

        item = next((i for i in order.items if i.id == item_id), None)
        if item is None:
            raise OrderError("Позиция не найдена в этом заказе")
        if len(order.items) == 1:
            raise OrderError("Это последняя позиция — удалите заказ целиком")

        order.items.remove(item)
        await self.db.delete(item)
        # Деньги за неё уже могли прийти: возврат — забота админа, заказ лишь
        # фиксирует, что покупатель в итоге получит.
        order.items_total = sum(i.price * i.qty for i in order.items)
        order.total = order.items_total + order.delivery_price

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
