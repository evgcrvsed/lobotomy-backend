"""Редактируемые из админки тексты витрины."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SiteSetting


class UnknownSettingError(Exception):
    """Ключа нет в списке известных — чтобы админка не насоздавала мусора."""


# Известные настройки: ключ -> (подпись в админке, значение по умолчанию).
# Добавить новый редактируемый текст = дописать строку сюда, схему БД не трогаем.
KNOWN_SETTINGS: dict[str, tuple[str, str]] = {
    "profile_greeting": ("Приветствие в профиле", "? ? ?"),
}

MAX_VALUE_LENGTH = 500


class SettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> dict[str, str]:
        """Все известные настройки: из БД, недостающие — со значением по умолчанию."""
        result = await self.db.execute(select(SiteSetting))
        stored = {row.key: row.value for row in result.scalars()}
        return {key: stored.get(key, default) for key, (_, default) in KNOWN_SETTINGS.items()}

    async def set(self, key: str, value: str) -> str:
        if key not in KNOWN_SETTINGS:
            raise UnknownSettingError(f"Неизвестная настройка «{key}»")

        value = value.strip()[:MAX_VALUE_LENGTH]
        if not value:
            # пустое поле — возвращаем значение по умолчанию, а не пустоту на витрине
            value = KNOWN_SETTINGS[key][1]

        setting = await self.db.get(SiteSetting, key)
        if setting is None:
            self.db.add(SiteSetting(key=key, value=value))
        else:
            setting.value = value
        await self.db.commit()
        return value
