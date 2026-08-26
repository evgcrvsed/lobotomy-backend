"""Отдельный процесс выгрузки заказов в Google-таблицу.

Кнопку жмут в админке, а ходит в Google этот контейнер. Почему не сам backend:
выгрузка сотни листов — это минуты сетевых запросов к чужому API со своими
лимитами и таймаутами, и держать на них веб-воркер незачем. Плюс gspread
синхронный, то есть в event loop приложения он вставал бы поперёк всех запросов.

Канал между админкой и этим процессом — таблица export_jobs в общей базе:
админка кладёт строку, воркер её забирает. Схемой он, как и cdek-воркер,
не владеет — таблицы создаёт backend, здесь только ждём их появления.

Запуск:
    python -m backend.workers.sheets
"""

import asyncio
import signal
from contextlib import suppress

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.config import settings
from backend.database import AsyncSessionLocal, engine
from backend.errors import setup_logging
from backend.services.sheets_export import configuration_problem, poll_forever, reset_stale_jobs

# Очередь задач: пока backend её не создал, забирать нечего
REQUIRED_TABLE = "export_jobs"
SCHEMA_WAIT_SECONDS = 180
SCHEMA_RETRY_SECONDS = 3
# Как часто просыпается ненастроенный воркер — просто чтобы поймать сигнал
IDLE_SLEEP_SECONDS = 3600


async def wait_for_schema() -> bool:
    """Ждёт, пока backend поднимет базу и создаст таблицы.

    DDL здесь принципиально не выполняем: владелец схемы один — веб-приложение.
    False — не дождались за отведённое время.
    """
    waited = 0
    while waited < SCHEMA_WAIT_SECONDS:
        try:
            async with AsyncSessionLocal() as db:
                found = await db.scalar(text(f"SELECT to_regclass('public.{REQUIRED_TABLE}')"))
            if found is not None:
                if waited:
                    print(f"[sheets] база готова (ждали {waited} с)")
                return True
            reason = f"таблицы {REQUIRED_TABLE} ещё нет"
        except (SQLAlchemyError, OSError) as e:
            # база ещё не поднялась — это норма в первые секунды после compose up
            reason = f"база недоступна: {type(e).__name__}"

        if waited == 0:
            print(f"[sheets] жду backend — {reason}")
        await asyncio.sleep(SCHEMA_RETRY_SECONDS)
        waited += SCHEMA_RETRY_SECONDS

    print(f"[sheets] backend не поднял схему за {SCHEMA_WAIT_SECONDS} с — выходим")
    return False


async def idle_forever(reason: str) -> None:
    """Живём, но ничего не делаем.

    Раньше в этом случае процесс просто выходил с кодом 0 — и при
    restart: unless-stopped Docker поднимал бы его по кругу, засыпая лог одной
    и той же строкой. Спящий контейнер честнее: в `docker compose ps` видно,
    что сервис есть и почему он ничего не делает.
    """
    print(f"{reason} — воркер простаивает, работать не с чем")
    while True:
        await asyncio.sleep(IDLE_SLEEP_SECONDS)


def install_shutdown(task: asyncio.Task) -> None:
    """SIGTERM от `docker stop` превращаем в отмену задачи.

    Без этого процесс умирает мгновенно, и задача навсегда остаётся в running —
    админка показывала бы «идёт выгрузка» до скончания века. С отменой она
    возвращается в очередь и доделается после перезапуска.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # add_signal_handler не поддерживается на Windows — там достаточно KeyboardInterrupt
        with suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(sig, task.cancel)


async def main() -> None:
    setup_logging(settings.debug)

    problem = configuration_problem()
    if problem is not None:
        # Не ошибка, а осознанная конфигурация. Не выходим: контейнер должен
        # остаться поднятым, иначе перезапуск по политике станет бесконечным.
        task = asyncio.create_task(idle_forever(f"[sheets] {problem}"))
    else:
        if not await wait_for_schema():
            raise SystemExit(1)
        await reset_stale_jobs()
        task = asyncio.create_task(poll_forever())
    install_shutdown(task)
    try:
        await task
    except asyncio.CancelledError:
        print("[sheets] остановка по сигналу")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
