"""任意位图 -> PNG 字节（换封面、WebP 升级为 PNG 用）。"""
from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from .models import CardParseError
from .png import is_png

_PNG_SAFE_MODES = {"1", "L", "LA", "P", "RGB", "RGBA", "I;16"}


def to_png_bytes(blob: bytes) -> bytes:
    """PNG 原样返回；其他格式（WebP/JPEG/GIF…）经 Pillow 解码后无损转 PNG，动图只取首帧。"""
    if is_png(blob):
        return blob
    try:
        with Image.open(io.BytesIO(blob)) as im:
            im.load()
            if im.mode not in _PNG_SAFE_MODES:
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            out = io.BytesIO()
            im.save(out, format="PNG")
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise CardParseError(f"无法解码为图片: {e}") from e
