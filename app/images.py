"""Работа с картинками: нормализация для Claude и для InSales."""
from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps

MAX_SIDE_FOR_CLAUDE = 1568  # больше Claude всё равно уменьшит
MAX_SIDE_FOR_SHOP = 2000


def normalize_jpeg(data: bytes, max_side: int, quality: int = 88) -> bytes:
    """Повернуть по EXIF, уменьшить до max_side по длинной стороне, вернуть JPEG."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    scale = max_side / max(w, h)
    if scale < 1:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def to_claude_image_block(data: bytes) -> dict:
    jpeg = normalize_jpeg(data, MAX_SIDE_FOR_CLAUDE)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()},
    }


def to_base64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode()
