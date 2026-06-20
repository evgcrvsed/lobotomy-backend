from pydantic import BaseModel, Field


class ProductImageCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    sort_order: int = Field(default=0, ge=0)


class ProductImageResponse(BaseModel):
    id: int
    filename: str
    sort_order: int

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    collection_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    material: str | None = Field(default=None, max_length=200)
    density: int | None = Field(default=None, gt=0, description="г/м²")
    price: int = Field(..., gt=0)
    images: list[ProductImageCreate] = Field(default_factory=list)


class ProductResponse(BaseModel):
    id: int
    collection_id: int
    name: str
    description: str | None
    material: str | None
    density: int | None
    price: int
    images: list[ProductImageResponse]

    model_config = {"from_attributes": True}
