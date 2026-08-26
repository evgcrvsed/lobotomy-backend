from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExportJobResponse(BaseModel):
    """Состояние выгрузки для админки: по нему кнопка и рисует свой текст."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str  # pending | running | done | error
    message: str | None
    rows_added: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SheetsExportStatus(BaseModel):
    """Что админка показывает про выгрузку: последняя задача и куда смотреть."""

    sheet_url: str | None  # None — выгрузка не настроена
    job: ExportJobResponse | None  # None — ни разу не запускали
