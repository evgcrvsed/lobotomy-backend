import io

from PIL import Image, ImageOps

# Больше этого размера по длинной стороне фото на сайте не нужны
MAX_DIMENSION = 1600
WEBP_QUALITY = 82
# Витрина белая — на этот фон и кладём картинки с прозрачностью
BACKGROUND = (255, 255, 255)


def _has_alpha(img: Image.Image) -> bool:
    """Есть ли в изображении прозрачность.

    Кроме привычных RGBA/LA прозрачность бывает у палитровых картинок (mode P):
    у них номер прозрачного цвета лежит отдельно, в info.
    """
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _on_white(img: Image.Image) -> Image.Image:
    """Кладёт изображение на белый фон и отдаёт RGB.

    Без этого прозрачный фон темнеет: обычный convert("RGB") подставляет под
    альфу чёрный, и товар оказывается на тёмном пятне вместо белой витрины.
    """
    if not _has_alpha(img):
        return img if img.mode == "RGB" else img.convert("RGB")

    rgba = img.convert("RGBA")
    canvas = Image.new("RGB", rgba.size, BACKGROUND)
    canvas.paste(rgba, mask=rgba.getchannel("A"))  # маска — альфа-канал самой картинки
    return canvas


def compress_image(content: bytes) -> bytes:
    """Уменьшает изображение до MAX_DIMENSION по длинной стороне и конвертирует в WebP.

    Прозрачность заменяется белым фоном. Бросает исключение, если content — не изображение.
    """
    img = Image.open(io.BytesIO(content))
    # применяем поворот из EXIF, иначе фото с телефона может лечь на бок
    img = ImageOps.exif_transpose(img)
    # до уменьшения: полупрозрачные края тогда смешиваются с белым, а не с пустотой
    img = _on_white(img)
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()


def needs_compression(path_suffix: str, content: bytes) -> bool:
    """True, если файл стоит пережать: не webp, крупнее MAX_DIMENSION или прозрачный."""
    if path_suffix.lower() != ".webp":
        return True
    img = Image.open(io.BytesIO(content))
    # прозрачный webp пропустить нельзя: на витрине он покажет фон, а не белое
    return max(img.size) > MAX_DIMENSION or _has_alpha(img)
