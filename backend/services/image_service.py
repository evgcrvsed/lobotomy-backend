import io

from PIL import Image, ImageOps

# Больше этого размера по длинной стороне фото на сайте не нужны
MAX_DIMENSION = 1600
WEBP_QUALITY = 82


def compress_image(content: bytes) -> bytes:
    """Уменьшает изображение до MAX_DIMENSION по длинной стороне и конвертирует в WebP.

    Бросает исключение, если content — не изображение.
    """
    img = Image.open(io.BytesIO(content))
    # применяем поворот из EXIF, иначе фото с телефона может лечь на бок
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()


def needs_compression(path_suffix: str, content: bytes) -> bool:
    """True, если файл стоит пережать: не webp или крупнее MAX_DIMENSION."""
    if path_suffix.lower() != ".webp":
        return True
    img = Image.open(io.BytesIO(content))
    return max(img.size) > MAX_DIMENSION
