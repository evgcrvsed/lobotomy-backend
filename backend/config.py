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

    app_name: str = "Lobotomy"
    app_version: str = "0.1.0"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/lobotomy"

    vk_client_id: str = ""  # ID приложения VK ID (id.vk.com); пусто — вход через VK выключен
    jwt_secret: str = "dev-secret-change-me-to-long-random-string"  # на сервере задать своё через переменную окружения
    jwt_ttl_days: int = 30

    # Email (Resend) — вход по одноразовому коду на почту
    resend_api_key: str = ""  # пусто — отправка почты выключена
    email_from: str = "noreply@lobo1omy.store"  # адрес отправителя; для реальных писем нужен свой домен
    # Отдельный адрес для писем о заказах — иначе "Заказ оплачен" приходило бы
    # от того же auth@, с которого шлют код входа, и выглядело странно
    email_from_orders: str = "orders@lobo1omy.store"
    email_code_ttl_minutes: int = 15  # срок жизни кода; 0 — код не протухает (небезопасно)
    email_code_resend_seconds: int = 30
    email_code_max_attempts: int = 5  # после стольких попыток код сгорает
    email_ip_limit_10min: int = 5
    email_ip_limit_hour: int = 15

    tinkoff_terminal_key: str = ""  # пусто — оплата выключена
    tinkoff_password: str = ""
    tinkoff_api_url: str = "https://securepay.tinkoff.ru/v2"
    # Фискальный чек (54-ФЗ): боевой терминал отклоняет Init без него
    # (ErrorCode 309, "expected.receipt") — проверено на реальном терминале.
    # Тестовый терминал тоже принимает чек нормально, поэтому шлём его всегда,
    # без развилки demo/боевой.
    #
    # ИП на патентной системе (ПСН) — подтверждено владельцем магазина.
    # Сумма патента (фиксированный платёж государству) тут ни при чём: она не
    # зависит от выручки и в чек/API не передаётся — нужен только сам факт,
    # что это патент. Другие варианты на будущее (другой ИП, смена режима):
    # usn_income, osn, usn_income_outcome, envd, esn
    tinkoff_receipt_taxation: str = "patent"
    # none — ПСН освобождена от НДС по патентному виду деятельности; варианты:
    # vat0, vat10, vat20, vat110, vat120 — если появится деятельность вне патента
    tinkoff_receipt_vat: str = "none"
    site_url: str = "https://lobo1omy.store"

    # СДЭК — автообновление статуса по трек-номеру.
    # Пустой client_id — интеграция выключена, заказы просто не опрашиваются.
    cdek_client_id: str = ""
    cdek_client_secret: str = ""
    cdek_api_url: str = "https://api.cdek.ru/v2"
    # Опрос экономный: СДЭК не присылает заголовков с остатком лимита,
    # поэтому держим запросы редкими и предсказуемыми, а не «сколько влезет».
    cdek_poll_interval_minutes: int = 20
    cdek_recheck_minutes: int = 120  # не чаще этого дёргаем один и тот же заказ
    cdek_batch_limit: int = 15
    cdek_request_delay_seconds: float = 1.0
    cdek_backoff_minutes: int = 60  # пауза после 429, прежде чем пробовать снова

    order_ip_limit_10min: int = 10
    # по истечении срока неоплаченный заказ отменяется
    pending_order_ttl_minutes: int = 60

    cors_origins: list[str] = ["http://localhost:5173"]

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
