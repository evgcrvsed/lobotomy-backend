from typing import Literal

from pydantic import BaseModel, Field, field_validator

ImageRole = Literal["main", "hover", "gallery", "sizechart"]

# Ограничения на размерную сетку: чтобы форма админки не разъехалась
# и в базу не уехал словарь произвольного размера
MAX_SIZE_COLUMNS = 8
MAX_COLUMN_NAME = 50
MAX_MEASUREMENT = 50


class ProductImageCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    role: ImageRole = "gallery"
    sort_order: int = Field(default=0, ge=0)


class ProductImageResponse(BaseModel):
    id: int
    filename: str
    role: ImageRole
    sort_order: int

    model_config = {"from_attributes": True}


class ProductSizeCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=10)
    # {название столбца: значение}; значение — строка, а не число: там пишут
    # и «46-48», и «one size», и замер с единицами измерения
    measurements: dict[str, str] = Field(default_factory=dict)

    @field_validator("measurements")
    @classmethod
    def _clean_measurements(cls, value: dict[str, str]) -> dict[str, str]:
        """Убирает пустые клетки — незаполненный замер просто не хранится."""
        cleaned = {}
        for name, measurement in value.items():
            name = name.strip()[:MAX_COLUMN_NAME]
            measurement = measurement.strip()[:MAX_MEASUREMENT]
            if name and measurement:
                cleaned[name] = measurement
        return cleaned


class ProductSizeResponse(BaseModel):
    id: int
    label: str
    measurements: dict[str, str]

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    collection_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    description: str | None = None
    material: str | None = Field(default=None, max_length=200)
    density: int | None = Field(default=None, gt=0, description="г/м²")
    price: int = Field(..., gt=0)
    # Порядок в каталоге. None — поставить в конец (текущий максимум + шаг)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    images: list[ProductImageCreate] = Field(default_factory=list)
    # Шапка размерной сетки — названия столбцов замеров в порядке показа
    size_columns: list[str] = Field(default_factory=list)
    sizes: list[ProductSizeCreate] = Field(default_factory=list)

    @field_validator("size_columns")
    @classmethod
    def _clean_columns(cls, value: list[str]) -> list[str]:
        """Выбрасывает пустые названия и повторы: имя столбца — это ключ замера,
        по двум одинаковым нельзя различить клетки."""
        cleaned = []
        for name in value:
            name = name.strip()[:MAX_COLUMN_NAME]
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned[:MAX_SIZE_COLUMNS]


class ProductResponse(BaseModel):
    id: int
    collection_id: int
    name: str
    slug: str | None
    description: str | None
    material: str | None
    density: int | None
    price: int
    sort_order: int
    images: list[ProductImageResponse]
    size_columns: list[str]
    sizes: list[ProductSizeResponse]

    model_config = {"from_attributes": True}
