"""Логирование ошибок и единый код обращения.

Пока приложение молчало о своих 4xx/5xx, разбор жалобы «не оформился заказ»
начинался с угадывания: человек видел в браузере «[object Object]», а на сервере
не оставалось ни поля, ни значения, ни даже названия браузера. Здесь всё, что
нужно, чтобы такой разбор занимал одну команду `docker logs`:

* каждому запросу выдаётся короткий код (заголовок X-Request-ID). Он же уходит
  клиенту в теле ошибки и показывается человеку — тот просто называет код,
  а мы ищем по нему в логе;
* 422 пишется вместе с полем, кодом ошибки и присланным значением;
* необработанное исключение — с трейсбеком и тем же кодом обращения;
* рядом всегда браузер и IP, поэтому «непонятный браузер» перестаёт быть непонятным.

Формат ответов при этом не меняется: `detail` остаётся ровно таким, каким его
отдаёт FastAPI, к нему лишь добавляется `request_id`.
"""

import logging
import secrets
import sys
import time
from contextlib import suppress

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.services.auth_service import client_ip

logger = logging.getLogger("lobotomy")

# Значение поля пишем обрезанным: там бывают адрес, почта и телефон, а в логе
# нужен не сам текст целиком, а понимание, что именно не подошло
MAX_LOGGED_VALUE = 120
# Дольше этого запрос считаем медленным и отмечаем отдельной строкой: именно
# на медленной сети вылезают гонки вроде «отправил форму раньше, чем загрузились справочники»
SLOW_REQUEST_SECONDS = 3.0
# 404 в логе не нужны: их генерируют боты и просто опечатки в адресе
QUIET_STATUSES = {404}


def setup_logging(debug: bool = False) -> None:
    """Единый формат для всех наших сообщений.

    uvicorn настраивает только свои логгеры и корневой не трогает, поэтому
    basicConfig здесь не конфликтует с ним и не приводит к двойным строкам.
    """
    # На Windows поток вывода берёт кодировку консоли (cp1251), и русский текст
    # в логе превращается в мусор — а при разборе ошибки читать нужно именно его
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _new_request_id() -> str:
    """Короткий код, который не стыдно попросить продиктовать по телефону."""
    return secrets.token_hex(4).upper()


def _short(value: object) -> str:
    # repr, а не str: иначе пустая строка и пробел выглядят в логе одинаково — никак.
    # Русский текст repr в Python 3 не экранирует, читаемость не страдает
    text = repr(value).replace("\n", " ")
    return text if len(text) <= MAX_LOGGED_VALUE else text[:MAX_LOGGED_VALUE] + "…"


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _who(request: Request) -> str:
    """Хвост строки лога: кто, откуда и чем пришёл."""
    return (
        f"id={request_id(request)} "
        f"ip={client_ip(request)} "
        f"ua={_short(request.headers.get('user-agent', '-'))}"
    )


def _describe(errors: list[dict]) -> str:
    """Ошибки валидации в одну строку: поле, машинный код, присланное значение.

    Именно `input` отвечает на главный вопрос «а что вообще прислали» — без него
    остаётся только гадать, какое из полей формы оказалось пустым.
    """
    parts = []
    for error in errors:
        # первый элемент loc — источник (body / query / path), в логе он бесполезен
        field = ".".join(str(part) for part in error.get("loc", [])[1:]) or "body"
        parts.append(f"{field}: {error.get('type')} (прислали {_short(error.get('input'))})")
    return "; ".join(parts)


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def tag_and_time(request: Request, call_next):
        request.state.request_id = _new_request_id()
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started

        response.headers["X-Request-ID"] = request.state.request_id
        if elapsed > SLOW_REQUEST_SECONDS:
            logger.warning(
                "SLOW %.1fs %s %s | %s", elapsed, request.method, request.url.path, _who(request)
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        logger.warning(
            "422 %s %s | %s | %s",
            request.method, request.url.path, _describe(errors), _who(request),
        )
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(errors), "request_id": request_id(request)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code >= 500:
            # наш собственный отказ (например, банк не ответил) — разбираться придётся
            logger.error(
                "%s %s %s | %s | %s",
                exc.status_code, request.method, request.url.path, _short(exc.detail), _who(request),
            )
        elif exc.status_code not in QUIET_STATUSES:
            logger.info(
                "%s %s %s | %s | %s",
                exc.status_code, request.method, request.url.path, _short(exc.detail), _who(request),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": jsonable_encoder(exc.detail), "request_id": request_id(request)},
            headers=exc.headers,  # 401 несёт WWW-Authenticate, его терять нельзя
        )

    @app.exception_handler(Exception)
    async def on_unhandled_error(request: Request, exc: Exception):
        """Падение, которое никто не поймал. Трейсбек — в лог, человеку — код обращения.

        Ответ отсюда идёт мимо остальных middleware, поэтому заголовок с кодом
        проставляем руками.
        """
        logger.exception(
            "500 %s %s | %s | %s",
            request.method, request.url.path, type(exc).__name__, _who(request),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Внутренняя ошибка сервера",
                "request_id": request_id(request),
            },
            headers={"X-Request-ID": request_id(request)},
        )
