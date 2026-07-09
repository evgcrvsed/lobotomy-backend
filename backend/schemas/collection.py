from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CollectionUpdate(CollectionCreate):
    image: str | None = Field(default=None, max_length=255)


class CollectionResponse(BaseModel):
    id: int
    name: str
    slug: str
    image: str | None

    model_config = {"from_attributes": True}
