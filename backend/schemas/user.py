from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: int
    auth_provider: str
    full_name: str | None
    email: str | None
    address: str | None
    city: str | None
    postal_code: str | None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)


class VkLoginRequest(BaseModel):
    access_token: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    token: str
    user: UserResponse
