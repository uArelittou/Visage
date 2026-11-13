"""缩略图：宽 360 的 WebP，按内容 hash 缓存到 <用户数据目录>\\thumbs\\<hash>.webp。"""
from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image

from .backup import atomic_write

THUMB_WIDTH = 360


class ThumbCache:
    def __init__(self, directory: Path, width: int = THUMB_WIDTH, quality: int = 80):
        self.dir = Path(directory)
        self.width = width
        self.quality = quality
        self.generated = 0  # 实际生成次数（测试/诊断用）
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def path_for(self, content_hash: str) -> Path:
        return self.dir / f"{content_hash}.webp"

    def get(self, content_hash: str, image_bytes: bytes) -> Path:
        """命中缓存直接返回；hash 不同（内容变了）则生成新文件。
        不放大小图：原图宽度不足 width 时保持原尺寸。"""
        out = self.path_for(content_hash)
        if out.is_file():
            return out
        # 卡库首屏会同时请求同一张缩略图（卡面和悬停背景）。不加锁时两个线程都去生成，
        # 后一个在 Windows 上替换正被前一个响应读着的文件，会失败或让响应长度对不上，卡面就显示成没封面
        with self._lock_for(content_hash):
            if out.is_file():
                return out
            return self._make(out, image_bytes)

    def _lock_for(self, content_hash: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(content_hash, threading.Lock())

    def _make(self, out: Path, image_bytes: bytes) -> Path:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im.seek(0)  # 动图只取首帧
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P", "PA") else "RGB")
            if im.width > self.width:
                h = max(1, round(im.height * self.width / im.width))
                im = im.resize((self.width, h), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="WEBP", quality=self.quality, method=4)
        atomic_write(out, buf.getvalue())
        self.generated += 1
        return out

    def prune(self, keep_hashes: set[str]) -> int:
        """清理不再被任何卡引用的缩略图。"""
        if not self.dir.is_dir():
            return 0
        n = 0
        for p in self.dir.glob("*.webp"):
            if p.stem not in keep_hashes:
                p.unlink(missing_ok=True)
                n += 1
        return n

    def clear(self) -> int:
        return self.prune(set())
