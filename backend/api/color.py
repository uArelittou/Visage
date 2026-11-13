"""封面主色：在缩略图上粗略分箱，偏向饱和度高的颜色，结果按内容 hash 缓存到 <用户数据目录>\\colors。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.library.backup import atomic_write

_SAMPLE = 48


def dominant_color(im: Image.Image) -> str | None:
    """返回 '#rrggbb'；全透明图返回 None。"""
    im = im.convert("RGBA")
    im.thumbnail((_SAMPLE, _SAMPLE))
    bins: dict[tuple[int, int, int], list[float]] = {}
    raw = im.tobytes()  # RGBA，每像素 4 字节；getdata 在 Pillow 13 起已弃用
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i:i + 4]
        if a < 128:
            continue
        hi, lo = max(r, g, b), min(r, g, b)
        sat = (hi - lo) / hi if hi else 0.0
        lum = (r * 299 + g * 587 + b * 114) / 1000
        weight = 0.25 + sat
        if lum < 24 or lum > 235:  # 近黑近白多半是背景/描边，压低权重
            weight *= 0.2
        acc = bins.setdefault((r >> 4, g >> 4, b >> 4), [0.0, 0.0, 0.0, 0.0, 0.0])
        acc[0] += r
        acc[1] += g
        acc[2] += b
        acc[3] += 1
        acc[4] += weight
    if not bins:
        return None
    best = max(bins.values(), key=lambda v: v[4])
    n = best[3]
    return "#{:02x}{:02x}{:02x}".format(round(best[0] / n), round(best[1] / n), round(best[2] / n))


def cached_color(cache_dir: Path, content_hash: str, thumb_path: Path) -> str | None:
    f = cache_dir / f"{content_hash}.txt"
    try:
        text = f.read_text(encoding="ascii").strip()
        if len(text) == 7 and text.startswith("#"):
            return text
    except (OSError, ValueError):
        pass
    with Image.open(thumb_path) as im:
        im.load()
        color = dominant_color(im)
    if color:
        atomic_write(f, color.encode("ascii"))
    return color
