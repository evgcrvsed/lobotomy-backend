"""Отправка почты через Resend — общая для кодов входа и писем о заказах."""

import httpx

from backend.config import settings

RESEND_API_URL = "https://api.resend.com/emails"


class EmailNotConfiguredError(Exception):
    """Не задан RESEND_API_KEY — отправка почты выключена."""


class EmailSendError(Exception):
    """Resend ответил ошибкой."""


async def send_email(to: str, subject: str, html: str) -> None:
    if not settings.resend_api_key:
        raise EmailNotConfiguredError("Отправка почты не настроена (нет RESEND_API_KEY)")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
        )
    if resp.status_code >= 300:
        raise EmailSendError(f"Resend вернул {resp.status_code}: {resp.text[:200]}")
