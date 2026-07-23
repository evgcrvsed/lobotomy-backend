import hashlib
import hmac
import secrets
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
RESEND_API_URL = "https://api.resend.com/emails"


class VkAuthError(Exception):
    pass


class EmailNotConfiguredError(Exception):
    pass


class EmailSendError(Exception):
    pass


def generate_login_code() -> str:
    """Шестизначный код, равномерно случайный."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_login_code(email: str, code: str) -> str:
    """Код хранится не в открытом виде: HMAC на секрете приложения."""
    msg = f"{email.lower()}:{code}".encode()
    return hmac.new(settings.jwt_secret.encode(), msg, hashlib.sha256).hexdigest()


async def send_login_code_email(email: str, code: str) -> None:
    if not settings.resend_api_key:
        raise EmailNotConfiguredError("Отправка почты не настроена (не задан RESEND_API_KEY)")

    html = (
        "<div style=\"font-family:sans-serif;font-size:15px;color:#111\">"
        "<p>Ваш код для входа в <strong>LOBOTOMY</strong>:</p>"
        f"<p style=\"font-size:30px;letter-spacing:6px;font-weight:700\">{code}</p>"
        "<p style=\"color:#888;font-size:13px\">Если вы не запрашивали вход — просто проигнорируйте письмо.</p>"
        "</div>"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [email], "subject": "Код для входа — LOBOTOMY", "html": html},
        )
    if resp.status_code >= 300:
        raise EmailSendError(f"Resend вернул {resp.status_code}: {resp.text[:200]}")


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


async def get_current_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нужны права администратора")
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
