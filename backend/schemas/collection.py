from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CollectionUpdate(CollectionCreate):
    image: str | None = Field(default=None, max_length=255)
    # None — флаг не трогаем. Иначе переименование коллекции сбрасывало бы
    # выбор главной картинки, ведь форма имени про этот флаг ничего не знает.
    is_hero: bool | None = None


class CollectionResponse(BaseModel):
    id: int
    name: str
    slug: str
    image: str | None
    is_hero: bool

    model_config = {"from_attributes": True}
