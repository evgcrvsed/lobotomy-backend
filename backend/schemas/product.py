from typing import Literal

from pydantic import BaseModel, Field

ImageRole = Literal["main", "hover", "gallery", "sizechart"]


class ProductImageCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    role: ImageRole = "gallery"
    sort_order: int = Field(default=0, ge=0)


class ProductImageResponse(BaseModel):
    id: int
    filename: str
    role: ImageRole
    sort_order: int

    model_config = {"from_attributes": True}


class ProductSizeCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=10)
    length: int | None = Field(default=None, ge=1, description="см")
    shoulder: int | None = Field(default=None, ge=1, description="см")
    chest: int | None = Field(default=None, ge=1, description="см")
    sleeve: int | None = Field(default=None, ge=1, description="см")


class ProductSizeResponse(BaseModel):
    id: int
    label: str
    length: int | None
    shoulder: int | None
    chest: int | None
    sleeve: int | None

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    collection_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    description: str | None = None
    material: str | None = Field(default=None, max_length=200)
    density: int | None = Field(default=None, gt=0, description="г/м²")
    price: int = Field(..., gt=0)
    images: list[ProductImageCreate] = Field(default_factory=list)
    sizes: list[ProductSizeCreate] = Field(default_factory=list)


class ProductResponse(BaseModel):
    id: int
    collection_id: int
    name: str
    slug: str | None
    description: str | None
    material: str | None
    density: int | None
    price: int
    images: list[ProductImageResponse]
    sizes: list[ProductSizeResponse]

    model_config = {"from_attributes": True}
