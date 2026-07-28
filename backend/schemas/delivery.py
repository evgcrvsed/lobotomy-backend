from pydantic import BaseModel, Field


class DeliveryMethodResponse(BaseModel):
    code: str
    label: str
    price: int
    index_label: str
    point_label: str
    sort_order: int

    model_config = {"from_attributes": True}


class DeliveryMethodUpdate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    price: int = Field(..., ge=0, le=1_000_000)
    index_label: str = Field(..., min_length=1, max_length=100)
    point_label: str = Field(..., min_length=1, max_length=100)
