from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CollectionResponse(BaseModel):
    id: int
    name: str
    slug: str

    model_config = {"from_attributes": True}
