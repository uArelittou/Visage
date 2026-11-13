"""原子写文件：同目录临时文件 + os.replace。"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    p = Path(path)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # Windows 上目标被杀软/预览/文件监听短暂占用会抛 PermissionError，重试几次
        for attempt in range(6):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
