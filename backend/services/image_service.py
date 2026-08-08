import io

from PIL import Image, ImageOps

# Больше этого размера по длинной стороне фото на сайте не нужны
MAX_DIMENSION = 1600
WEBP_QUALITY = 82


def _has_alpha(img: Image.Image) -> bool:
    """Есть ли в изображении прозрачность.

    Кроме привычных RGBA/LA прозрачность бывает у палитровых картинок (mode P):
    у них номер прозрачного цвета лежит отдельно, в info.
    """
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _to_web_mode(img: Image.Image) -> Image.Image:
    """RGBA для картинок с прозрачностью, RGB для всех остальных.

    Прозрачность сохраняем: подложку под фото задаёт вёрстка, и залитый в файл
    фон потом уже не убрать. Но и convert("RGB") напрямую звать нельзя — он
    подставляет под альфу чёрный, из-за чего палитровые PNG чернели.
    """
    if _has_alpha(img):
        return img if img.mode == "RGBA" else img.convert("RGBA")
    return img if img.mode == "RGB" else img.convert("RGB")


def compress_image(content: bytes) -> bytes:
    """Уменьшает изображение до MAX_DIMENSION по длинной стороне и конвертирует в WebP.

    Прозрачность сохраняется. Бросает исключение, если content — не изображение.
    """
    img = Image.open(io.BytesIO(content))
    # применяем поворот из EXIF, иначе фото с телефона может лечь на бок
    img = ImageOps.exif_transpose(img)
    img = _to_web_mode(img)
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
