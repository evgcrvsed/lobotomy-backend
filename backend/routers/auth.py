from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import User
from backend.schemas.user import AuthResponse, UserResponse, UserUpdate, VkLoginRequest
from backend.services.auth_service import VkAuthError, create_token, fetch_vk_user, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/vk", response_model=AuthResponse)
async def vk_login(data: VkLoginRequest, db: DbDep):
    if not settings.vk_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Вход через VK ID не настроен (не задан VK_CLIENT_ID)",
        )

    try:
        vk_user = await fetch_vk_user(data.access_token)
    except VkAuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    vk_id = str(vk_user["user_id"])
    result = await db.execute(select(User).where(User.vk_id == vk_id))
    user = result.scalar_one_or_none()

    if user is None:
        name_parts = [vk_user.get("last_name"), vk_user.get("first_name")]
        user = User(
            auth_provider="vk",
            vk_id=vk_id,
            full_name=" ".join(p for p in name_parts if p) or None,
            email=vk_user.get("email"),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return {"token": create_token(user.id), "user": user}


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser):
    return user


@router.put("/me", response_model=UserResponse)
async def update_me(data: UserUpdate, user: CurrentUser, db: DbDep):
    user.full_name = data.full_name
    user.email = data.email
    user.address = data.address
    user.city = data.city
    user.postal_code = data.postal_code
    await db.commit()
    await db.refresh(user)
    return user
