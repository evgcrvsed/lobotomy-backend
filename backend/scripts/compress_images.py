"""Одноразовое сжатие уже загруженных фотографий.

Что делает:
- каждый файл из static/images пережимает в WebP (до 1600px по длинной стороне);
- оригинал переносит в static/originals (ничего не удаляется);
- обновляет ссылки на файлы в базе данных.

Файлы, которые уже в WebP и не крупнее 1600px, пропускаются —
скрипт можно запускать сколько угодно раз.

Запуск в докере:   docker compose exec backend python -m backend.scripts.compress_images
Локально (dev):    python -m backend.scripts.compress_images
"""

import asyncio
import shutil

from sqlalchemy import update

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import ProductImage
from backend.services.image_service import compress_image, needs_compression

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _unique_name(directory, base_name: str) -> str:
    """Возвращает свободное имя файла в directory (base_name или с суффиксом -2, -3...)."""
    stem, _, ext = base_name.rpartition(".")
    candidate = base_name
    n = 2
    while (directory / candidate).exists():
        candidate = f"{stem}-{n}.{ext}"
        n += 1
    return candidate


async def main() -> None:
    images_dir = settings.static_dir / "images"
    originals_dir = settings.static_dir / "originals"
    originals_dir.mkdir(parents=True, exist_ok=True)

    total_before = 0
    total_after = 0
    processed = 0

    async with AsyncSessionLocal() as session:
        for path in sorted(images_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue

            content = path.read_bytes()
            try:
                if not needs_compression(path.suffix, content):
                    print(f"{path.name}: уже сжат, пропускаю")
                    continue
                compressed = compress_image(content)
            except Exception as e:
                print(f"{path.name}: не удалось обработать ({e}), пропускаю")
                continue

            new_name = _unique_name(images_dir, f"{path.stem}.webp")

            # оригинал — в сторонку, сжатую версию — на его место
            shutil.move(str(path), str(originals_dir / path.name))
            (images_dir / new_name).write_bytes(compressed)

            if new_name != path.name:
                await session.execute(
                    update(ProductImage)
                    .where(ProductImage.filename == path.name)
                    .values(filename=new_name)
                )

            total_before += len(content)
            total_after += len(compressed)
            processed += 1
            print(f"{path.name}: {len(content) // 1024} КБ -> {new_name}: {len(compressed) // 1024} КБ")

        await session.commit()

    if processed:
        print(
            f"\nГотово: {processed} файл(ов), "
            f"{total_before // 1024 // 1024} МБ -> {total_after // 1024} КБ. "
            f"Оригиналы в {originals_dir}"
        )
    else:
        print("Сжимать нечего — все файлы уже в порядке.")


if __name__ == "__main__":
    asyncio.run(main())
