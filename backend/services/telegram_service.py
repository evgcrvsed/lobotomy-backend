"""Уведомления в Telegram — например, админу о новой оплате.

Служебный канал «отправил и забыл»: не дошло — не беда, ничего важного на этом
не завязано. Поэтому функции здесь НИКОГДА не бросают исключений наружу —
вызывающий код (вебхук Т-Банка) не должен падать из-за недоступного телеграма.
"""

import asyncio

import httpx

from backend.config import settings

# Ссылки на запущенные фоновые задачи. Без этого сборщик мусора может убить
# задачу на середине: asyncio держит на них только слабые ссылки.
_background_tasks: set[asyncio.Task] = set()


def is_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_admin_chat_id)


async def send_message(text: str, chat_id: str | None = None) -> bool:
    """Отправляет сообщение. Возвращает True, если дошло.

    Ошибки не пробрасывает — только пишет в лог.
    """
    if not is_configured():
        return False

    chat = chat_id or settings.telegram_admin_chat_id
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "chat_id": chat,
                "text": text,
                # HTML вместо Markdown: не ломается о случайные _ * ` в данных заказа
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
        data = resp.json()
        if not data.get("ok"):
            print(f"[telegram] не отправлено: {data.get('description') or data}")
            return False
        return True
    except Exception as e:
        # Ловим всё: сеть, таймаут, кривой JSON. Уведомление не стоит того,
        # чтобы из-за него падал вызывающий код.
        print(f"[telegram] не отправлено: {type(e).__name__}: {e}")
        return False


def notify(text: str, chat_id: str | None = None) -> None:
    """Отправка в фоне: не блокирует вызывающий код.

    Нужна там, где ответ надо вернуть быстро — например, в вебхуке Т-Банка:
    он ждёт «OK», и если мы будем ждать телеграм, он может отвалиться по
    таймауту и прислать уведомление повторно.
    """
    if not is_configured():
        return

    task = asyncio.create_task(send_message(text, chat_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
