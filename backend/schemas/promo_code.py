from datetime import date

from pydantic import BaseModel, Field


class PromoCodeCreate(BaseModel):
    # Только латиница, цифры, дефис и подчёркивание: код диктуют в переписке
    # и вводят руками, поэтому ни пробелов, ни похожей на латиницу кириллицы
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    # Максимум 99, а не 100: заказ на 0 рублей ломает оплату — банку нечего
    # проводить и не на что выбивать чек. Пусть заплатит хотя бы рубль.
    discount_percent: int = Field(..., ge=1, le=99)
    # None — без ограничения по числу применений
    max_activations: int | None = Field(default=None, ge=1, le=1_000_000)
    # None — бессрочный
    expires_at: date | None = None


class PromoCodeResponse(BaseModel):
    id: int
    code: str
    discount_percent: int
    max_activations: int | None
    used_count: int
    expires_at: date | None

    model_config = {"from_attributes": True}
