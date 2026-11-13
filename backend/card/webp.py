"""WebP 读取。WebP 无法就地写回卡数据，保存时统一升级为 PNG（与参考项目 file:saveCard 一致）。"""
from __future__ import annotations

import struct

from .deepscan import deep_scan_for_json

_IMAGE_FOURCCS = {b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF", b"ICCP"}


def is_webp(blob: bytes) -> bool:
    return len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP"


def iter_riff_chunks(blob: bytes) -> list[tuple[bytes, bytes]]:
    """顶层 RIFF 子块 (fourcc, payload)；越界即停，不抛异常。"""
    out: list[tuple[bytes, bytes]] = []
    off = 12
    n = len(blob)
    while off + 8 <= n:
        fourcc = blob[off:off + 4]
        (size,) = struct.unpack_from("<I", blob, off + 4)
        payload = blob[off + 8:off + 8 + size]
        out.append((fourcc, payload))
        off += 8 + size + (size & 1)
    return out


def extract_card_json(blob: bytes) -> dict | None:
    """先扫描元数据块（EXIF/XMP/自定义块），未命中再整文件深度扫描。"""
    meta = b"\n".join(p for fcc, p in iter_riff_chunks(blob) if fcc not in _IMAGE_FOURCCS)
    if meta:
        found = deep_scan_for_json(meta)
        if found is not None:
            return found
    return deep_scan_for_json(blob)
