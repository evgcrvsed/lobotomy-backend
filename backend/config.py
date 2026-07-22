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
