from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class OrderItemIn(BaseModel):
    product_id: int
    size: str | None = None
    qty: int = Field(..., ge=1)


class OrderCreate(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    delivery_method: str = Field(..., pattern="^(cdek|post|cis)$")
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=20)
    pickup_point: str | None = Field(default=None, max_length=500)
    items: list[OrderItemIn] = Field(..., min_length=1)


class OrderItemResponse(BaseModel):
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
    created_at: datetime
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}


class OrderCreated(BaseModel):
    number: str
    payment_url: str


class OrderTrackingUpdate(BaseModel):
    tracking_number: str | None = Field(default=None, max_length=100)
