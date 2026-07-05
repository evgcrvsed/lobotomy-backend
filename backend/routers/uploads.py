import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import Product, ProductImage
from backend.services.image_service import compress_image

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

DbDep = Annotated[AsyncSession, Depends(get_db)]

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# Входной файл может быть большим — после сжатия на диск ляжет в разы меньше
MAX_SIZE = 20 * 1024 * 1024  # 20 МБ


def _images_dir() -> Path:
    return settings.static_dir / "images"


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
            detail="Файл слишком большой (максимум 20 МБ)",
        )

    try:
        compressed = compress_image(content)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл повреждён или не является изображением",
        )

    # uuid вместо исходного имени: исключает коллизии и небезопасные символы
    filename = f"{uuid.uuid4().hex}.webp"
    dest = _images_dir() / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(compressed)

    return {"filename": filename}


@router.get("/images")
async def list_images(db: DbDep):
    result = await db.execute(
        select(ProductImage.filename, Product.name).join(Product, ProductImage.product_id == Product.id)
    )
    usage: dict[str, list[str]] = {}
    for filename, product_name in result.all():
        names = usage.setdefault(filename, [])
        if product_name not in names:
            names.append(product_name)

    images_dir = _images_dir()
    files = [p for p in images_dir.iterdir() if p.is_file()] if images_dir.is_dir() else []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return [
        {"filename": p.name, "size": p.stat().st_size, "products": usage.get(p.name, [])}
        for p in files
    ]


@router.delete("/images/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(filename: str, db: DbDep):
    # защита от путей вида ../../etc/passwd
    if Path(filename).name != filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректное имя файла")

    result = await db.execute(
        select(Product.name)
        .join(ProductImage, ProductImage.product_id == Product.id)
        .where(ProductImage.filename == filename)
    )
    used_by = list(dict.fromkeys(result.scalars().all()))
    if used_by:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Файл используется: {', '.join(used_by)}. Сначала замените фото у товара.",
        )

    path = _images_dir() / filename
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    path.unlink()
