import hmac
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import LoginCode, User
from backend.schemas.user import (
    AuthResponse,
    EmailCodeRequest,
    EmailCodeVerify,
    UserResponse,
    UserUpdate,
    VkLoginRequest,
)
from backend.services.auth_service import (
    EmailNotConfiguredError,
    EmailSendError,
    VkAuthError,
    create_token,
    fetch_vk_user,
    generate_login_code,
    get_current_user,
    hash_login_code,
    send_login_code_email,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/email/request")
async def request_email_code(data: EmailCodeRequest, db: DbDep):
    email = data.email.strip().lower()
    now = datetime.now(timezone.utc)

    # антиспам: не чаще одного письма раз в N секунд
    recent = await db.execute(
        select(LoginCode).where(LoginCode.email == email).order_by(LoginCode.created_at.desc())
    )
    last = recent.scalars().first()
    if last and last.created_at and (now - last.created_at).total_seconds() < settings.email_code_resend_seconds:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Код уже отправлен, подождите немного",
        )

    # один активный код на почту — старые убираем
    await db.execute(delete(LoginCode).where(LoginCode.email == email))
    code = generate_login_code()
    expires_at = now + timedelta(minutes=settings.email_code_ttl_minutes) if settings.email_code_ttl_minutes else None
    db.add(LoginCode(email=email, code_hash=hash_login_code(email, code), expires_at=expires_at))
    await db.commit()

    try:
        await send_login_code_email(email, code)
    except EmailNotConfiguredError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except EmailSendError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    return {"sent": True}


@router.post("/email/verify", response_model=AuthResponse)
async def verify_email_code(data: EmailCodeVerify, db: DbDep):
    email = data.email.strip().lower()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(LoginCode).where(LoginCode.email == email).order_by(LoginCode.created_at.desc())
    )
    login_code = result.scalars().first()
    if login_code is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала запросите код")

    if login_code.expires_at and login_code.expires_at < now:
        await db.execute(delete(LoginCode).where(LoginCode.email == email))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Код истёк, запросите новый")

    if login_code.attempts >= 5:
        await db.execute(delete(LoginCode).where(LoginCode.email == email))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Слишком много попыток")

    if not hmac.compare_digest(login_code.code_hash, hash_login_code(email, data.code.strip())):
        login_code.attempts += 1
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный код")

    # код верный — гасим его и входим
    await db.execute(delete(LoginCode).where(LoginCode.email == email))

    found = await db.execute(select(User).where(func.lower(User.email) == email))
    user = found.scalar_one_or_none()
    if user is None:
        user = User(auth_provider="email", email=email)
        db.add(user)
    await db.commit()
    await db.refresh(user)

    return {"token": create_token(user.id), "user": user}


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
