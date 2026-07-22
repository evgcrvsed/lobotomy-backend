import time
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import User

_bearer = HTTPBearer(auto_error=False)

VK_USER_INFO_URL = "https://id.vk.ru/oauth2/user_info"


class VkAuthError(Exception):
    pass


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": int(time.time()) + settings.jwt_ttl_days * 86400,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизован")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


async def fetch_vk_user(access_token: str) -> dict:
    """Проверяет VK-токен и возвращает данные пользователя от VK ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            VK_USER_INFO_URL,
            data={"access_token": access_token, "client_id": settings.vk_client_id},
        )
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or "user" not in data:
        raise VkAuthError(data.get("error_description", "VK не подтвердил токен"))
    return data["user"]
