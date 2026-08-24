"""Отдельный процесс автообновления статусов СДЭК.

Раньше опрос жил внутри веб-приложения — asyncio-задачей в lifespan main.py.
Это давало три неудобства: рестарт API обрывал проход на середине, перезапустить
один только опрос было нельзя, а его сообщения терялись в общем логе запросов.

Теперь это самостоятельный контейнер поверх той же базы. Схемой он не владеет:
таблицы создаёт и досоздаёт backend, поэтому на старте воркер просто ждёт, пока
нужная таблица появится, и ничего не мигрирует сам.

Запуск:
    python -m backend.workers.cdek
"""

import asyncio
import signal
from contextlib import suppress

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.errors import setup_logging
from backend.services.cdek_service import is_configured
from backend.services.cdek_sync import poll_forever

# Таблица, ради которой воркер и живёт: пока backend её не создал, работать не с чем
REQUIRED_TABLE = "orders"
SCHEMA_WAIT_SECONDS = 180
SCHEMA_RETRY_SECONDS = 3


async def wait_for_schema() -> bool:
    """Ждёт, пока backend поднимет базу и создаст таблицы.

    DDL здесь принципиально не выполняем: два процесса, одновременно
    делающих create_all/ALTER, блокируют друг друга на ровном месте.
    Владелец схемы один — веб-приложение, воркер только дожидается результата.

    False — не дождались за отведённое время (см. вызывающий код).
    """
    waited = 0
    while waited < SCHEMA_WAIT_SECONDS:
        try:
            async with AsyncSessionLocal() as db:
                found = await db.scalar(text(f"SELECT to_regclass('public.{REQUIRED_TABLE}')"))
            if found is not None:
                if waited:
                    print(f"[cdek] база готова (ждали {waited} с)")
                return True
            reason = f"таблицы {REQUIRED_TABLE} ещё нет"
        except (SQLAlchemyError, OSError) as e:
            # база ещё не поднялась — это норма в первые секунды после compose up
            reason = f"база недоступна: {type(e).__name__}"

        if waited == 0:
            print(f"[cdek] жду backend — {reason}")
        await asyncio.sleep(SCHEMA_RETRY_SECONDS)
        waited += SCHEMA_RETRY_SECONDS

    print(f"[cdek] backend не поднял схему за {SCHEMA_WAIT_SECONDS} с — выходим")
    return False


def install_shutdown(task: asyncio.Task) -> None:
    """SIGTERM от `docker stop` превращаем в отмену задачи.

    Без этого процесс умирает мгновенно и может не дойти до db.commit() —
    проверенные в этом проходе заказы просто перепроверятся в следующий раз,
    но лишний запрос к СДЭК при экономном лимите терять не хочется.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # add_signal_handler не поддерживается на Windows — там достаточно KeyboardInterrupt
        with suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(sig, task.cancel)


async def main() -> None:
    setup_logging(settings.debug)

    if not is_configured():
        # Не ошибка, а осознанная конфигурация: без ключей опрашивать нечем.
        # Контейнер завершится с кодом 0 и (при restart: on-failure) не будет
        # перезапускаться по кругу — в логе останется одна внятная строка.
        print("[cdek] воркер не запущен: не задан CDEK_CLIENT_ID")
        return

    if not await wait_for_schema():
        raise SystemExit(1)

    task = asyncio.create_task(poll_forever())
    install_shutdown(task)
    try:
        await task
    except asyncio.CancelledError:
        print("[cdek] остановка по сигналу")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
