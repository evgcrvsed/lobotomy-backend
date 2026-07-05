import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from backend.config import settings

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIZE = 10 * 1024 * 1024  # 10 МБ


@router.post("/image", status_code=status.HTTP_201_CREATED)
async def upload_image(file: UploadFile):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Допустимы только JPG, PNG и WebP",
        )

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл слишком большой (максимум 10 МБ)",
        )

    # uuid вместо исходного имени: исключает коллизии и небезопасные символы
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = settings.static_dir / "images" / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    return {"filename": filename}
