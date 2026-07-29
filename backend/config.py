from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Lobotomy"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/lobotomy"

    # Auth
    vk_client_id: str = ""  # ID приложения VK ID (id.vk.com); пусто — вход через VK выключен
    jwt_secret: str = "dev-secret-change-me-to-long-random-string"  # на сервере задать своё через переменную окружения
    jwt_ttl_days: int = 30

    # Email (Resend) — вход по одноразовому коду на почту
    resend_api_key: str = ""  # пусто — отправка почты выключена
    email_from: str = "noreply@lobo1omy.store"  # адрес отправителя; для реальных писем нужен свой домен
    email_code_ttl_minutes: int = 15  # срок жизни кода; 0 — код не протухает (небезопасно)
    email_code_resend_seconds: int = 30  # не чаще одного запроса кода на почту за это время
    email_code_max_attempts: int = 5  # после стольких неверных попыток код сгорает
    # Антиспам по IP: сколько писем с кодом можно запросить с одного адреса
    email_ip_limit_10min: int = 5
    email_ip_limit_hour: int = 15

    # Оплата (Т-Банк / Tinkoff)
    tinkoff_terminal_key: str = ""  # пусто — оплата выключена
    tinkoff_password: str = ""
    tinkoff_api_url: str = "https://securepay.tinkoff.ru/v2"
    tinkoff_send_receipt: bool = False  # слать фискальный чек (включить на боевом терминале с фискализацией)
    site_url: str = "https://lobo1omy.store"  # база для webhook/success/fail и писем

    # СДЭК — автообновление статуса по трек-номеру.
    # Пустой client_id — интеграция выключена, заказы просто не опрашиваются.
    cdek_client_id: str = ""
    cdek_client_secret: str = ""
    cdek_api_url: str = "https://api.cdek.ru/v2"
    # Опрос экономный: СДЭК не присылает заголовков с остатком лимита,
    # поэтому держим запросы редкими и предсказуемыми, а не «сколько влезет».
    cdek_poll_interval_minutes: int = 20  # как часто просыпается фоновый опрос
    cdek_recheck_minutes: int = 120  # не чаще этого дёргаем ОДИН и тот же заказ
    cdek_batch_limit: int = 15  # сколько заказов проверяем за один проход
    cdek_request_delay_seconds: float = 1.0  # пауза между запросами внутри прохода
    cdek_backoff_minutes: int = 60  # пауза после 429, прежде чем пробовать снова

    # Доставка: способы и цены хранятся в БД (таблица delivery_methods),
    # редактируются в админке. Здесь только антиспам.
    # Антиспам заказов: сколько заказов можно создать с одного IP за 10 минут
    order_ip_limit_10min: int = 10
    # Через сколько минут неоплаченный заказ считается брошенным и отменяется
    pending_order_ttl_minutes: int = 60

    # CORS — источники, которым разрешено ходить в API из браузера
    cors_origins: list[str] = ["http://localhost:5173"]

    # Paths
    static_dir: Path = ROOT_DIR / "static"

    @field_validator("port")
    @classmethod
    def port_must_be_valid(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port must be between 1 and 65535, got {v}")
        return v

    @field_validator("static_dir")
    @classmethod
    def static_dir_must_exist(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"static_dir does not exist: {v}")
        return v


settings = Settings()
