from pydantic import BaseModel


class CollectionResponse(BaseModel):
    id: int
    name: str
    slug: str

    model_config = {"from_attributes": True}
