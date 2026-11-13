"""角色卡读写入口：load_card / read_image_bytes / save_card。支持 .png / .webp / .json。"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Iterator

from . import png, webp
from .deepscan import deep_scan_for_json
from .fsio import atomic_write_bytes
from .image import to_png_bytes
from .models import SPEC_V3, Card, CardParseError, CardWriteError
from .validate import get_card_reject_reason, is_character_card_data

__all__ = ["load_card", "read_image_bytes", "save_card", "Card", "CardParseError", "CardWriteError"]

_SUPPORTED_EXTS = {".png", ".webp", ".json"}


def _dumps(obj: object, indent: int | None = None) -> bytes:
    seps = (",", ":") if indent is None else None
    try:
        return json.dumps(obj, ensure_ascii=False, indent=indent, separators=seps).encode("utf-8")
    except UnicodeEncodeError:  # JSON 里含孤立代理字符时退回 \uXXXX 转义，保证可回读
        return json.dumps(obj, ensure_ascii=True, indent=indent, separators=seps).encode("ascii")


def _candidates(blob: bytes, suffix: str) -> Iterator[dict]:
    """按优先级惰性产出候选卡 JSON：PNG 为 ccv3 > chara > 深度扫描。"""
    if png.is_png(blob):
        _, chunks, _ = png.parse_chunks(blob)
        payloads = png.extract_payloads(chunks)
        for kw in ("ccv3", "chara"):
            if kw in payloads:
                yield payloads[kw]
        found = deep_scan_for_json(blob)  # 损坏 PNG / 非标准块的兜底
        if found is not None:
            yield found
    elif webp.is_webp(blob):
        found = webp.extract_card_json(blob)
        if found is not None:
            yield found
    else:
        head = blob.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
        if suffix != ".json" and head not in (b"{", b"["):
            raise CardParseError("不支持的文件格式（仅 PNG / WebP / JSON）")
        try:
            yield json.loads(blob.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as e:
            raise CardParseError(f"JSON 解析失败: {e}") from e


def _parse_bytes(blob: bytes, suffix: str) -> Card:
    first_reason: str | None = None
    for cand in _candidates(blob, suffix):
        if is_character_card_data(cand):
            return Card.from_dict(cand)
        first_reason = first_reason or get_card_reject_reason(cand)
    raise CardParseError(f"不是角色卡: {first_reason}" if first_reason else "未找到角色卡数据")


def load_card(path: str | Path) -> Card:
    p = Path(path)
    return _parse_bytes(p.read_bytes(), p.suffix.lower())


def read_image_bytes(path: str | Path) -> bytes | None:
    """封面原图字节（PNG/WebP 文件本身）；JSON 卡没有封面，返回 None。"""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return None
    blob = p.read_bytes()
    if png.is_png(blob) or webp.is_webp(blob):
        return blob
    raise CardParseError("不是 PNG / WebP 图片")


def save_card(path: str | Path, card: Card, *, image_bytes: bytes | None = None) -> Path:
    """原子写回卡片，返回实际写入的路径。

    - .png：重写 chara(V2) + ccv3(V3) 两个 tEXt 块，其余块字节原样保留。
    - .webp：无法就地写回，升级为同名 .png 并删除原 .webp（参考项目同款行为）。
    - .json：直接写（V3 卡写 V3，其余写 V2）；给了 image_bytes 时同样升级为 .png。
    - image_bytes：替换封面（任意 Pillow 可解码格式，统一转 PNG）。
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in _SUPPORTED_EXTS:
        raise CardParseError(f"不支持的格式: {ext or '(无扩展名)'}")

    if ext == ".json" and image_bytes is None:
        obj = card.to_v3_dict() if card.spec == SPEC_V3 else card.to_v2_dict()
        atomic_write_bytes(p, _dumps(obj, indent=2))
        return p

    base = to_png_bytes(image_bytes if image_bytes is not None else p.read_bytes())
    v2, v3 = card.to_v2_dict(), card.to_v3_dict()
    payloads = {
        "chara": base64.b64encode(_dumps(v2)),
        "ccv3": base64.b64encode(_dumps(v3)),
    }
    out = png.embed_payloads(base, payloads)

    # 写前回读校验：内嵌数据必须能原样读回，否则宁可不写
    _, chunks, _ = png.parse_chunks(out)
    back = png.extract_payloads(chunks)
    if back.get("chara") != v2 or back.get("ccv3") != v3:
        raise CardWriteError("写前校验失败：内嵌卡数据无法原样读回")

    target = p if ext == ".png" else p.with_suffix(".png")
    if target != p and target.exists():
        raise CardWriteError(f"目标已存在，拒绝覆盖: {target}")
    atomic_write_bytes(target, out)
    if target != p and p.exists():
        p.unlink()
    return target
