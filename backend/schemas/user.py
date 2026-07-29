from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: int
    auth_provider: str
    is_admin: bool
    full_name: str | None
    email: str | None
    phone: str | None
    country: str | None
    city: str | None
    address: str | None
    postal_code: str | None
    pickup_point: str | None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """Правка своего профиля. Почты здесь нет намеренно: она подтверждена
    входом и служит ключом аккаунта — менять её нельзя."""

    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=20)
    pickup_point: str | None = Field(default=None, max_length=500)


class VkLoginRequest(BaseModel):
    access_token: str = Field(..., min_length=1)


class EmailCodeRequest(BaseModel):
    email: EmailStr


class EmailCodeVerify(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=8)


class AuthResponse(BaseModel):
    token: str
    user: UserResponse
