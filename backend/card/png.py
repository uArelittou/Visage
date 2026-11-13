"""PNG 块级读写。写回时只增删 chara/ccv3 文本块，其余块按原始字节原样保留（含原 CRC）。"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .deepscan import decode_base64_json
from .models import CardParseError

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CARD_KEYWORDS = ("chara", "ccv3")
_MAX_INFLATE = 64 * 1024 * 1024


@dataclass(frozen=True)
class Chunk:
    type: bytes
    data: bytes
    raw: bytes  # 含 length/type/data/crc 的原始字节


def is_png(blob: bytes) -> bool:
    # 与参考项目一致，只校验前 4 字节魔数
    return blob[:4] == PNG_SIG[:4]


def parse_chunks(blob: bytes) -> tuple[bytes, list[Chunk], bytes]:
    """返回 (8 字节签名, 块列表, IEND 之后的尾部字节)。块越界/截断时停止解析，不抛异常。"""
    if len(blob) < 8 or not is_png(blob):
        raise CardParseError("不是 PNG 文件")
    chunks: list[Chunk] = []
    off = 8
    n = len(blob)
    while off + 12 <= n:
        (length,) = struct.unpack_from(">I", blob, off)
        end = off + 12 + length
        if end > n:
            break
        ctype = blob[off + 4:off + 8]
        chunks.append(Chunk(ctype, blob[off + 8:off + 8 + length], blob[off:end]))
        off = end
        if ctype == b"IEND":
            break
    has_iend = bool(chunks) and chunks[-1].type == b"IEND"
    return blob[:8], chunks, (blob[off:] if has_iend else b"")


def _inflate(data: bytes) -> bytes:
    d = zlib.decompressobj()
    out = d.decompress(data, _MAX_INFLATE)
    if d.unconsumed_tail:
        raise ValueError("压缩文本块过大")
    return out


def parse_text_chunk(chunk: Chunk) -> tuple[str, bytes] | None:
    """tEXt / zTXt / iTXt -> (keyword, 文本字节)。结构不合法返回 None。"""
    t, d = chunk.type, chunk.data
    if t not in (b"tEXt", b"zTXt", b"iTXt"):
        return None
    kw, sep, rest = d.partition(b"\0")
    if not sep or not kw:
        return None
    keyword = kw.decode("latin-1")
    try:
        if t == b"tEXt":
            return keyword, rest
        if t == b"zTXt":
            return keyword, _inflate(rest[1:])
        flag = rest[0]
        rest = rest[2:]  # 跳过 compression_flag + compression_method
        _lang, _, rest = rest.partition(b"\0")
        _trans, _, text = rest.partition(b"\0")
        return keyword, (_inflate(text) if flag else text)
    except (IndexError, zlib.error, ValueError):
        return None


def extract_payloads(chunks: list[Chunk]) -> dict[str, dict]:
    """每个 chara/ccv3 关键字取第一个能成功解码为 JSON 对象的块（首块损坏会继续找后续块）。"""
    found: dict[str, dict] = {}
    for ch in chunks:
        parsed = parse_text_chunk(ch)
        if parsed is None:
            continue
        keyword, text = parsed
        if keyword not in CARD_KEYWORDS or keyword in found:
            continue
        try:
            obj = decode_base64_json(text)
        except ValueError:
            continue
        if isinstance(obj, dict):
            found[keyword] = obj
    return found


def _build_chunk(ctype: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def _is_card_chunk(chunk: Chunk) -> bool:
    if chunk.type not in (b"tEXt", b"zTXt", b"iTXt"):
        return False
    kw, sep, _ = chunk.data.partition(b"\0")
    return bool(sep) and kw.decode("latin-1") in CARD_KEYWORDS


def embed_payloads(blob: bytes, payloads: dict[str, bytes]) -> bytes:
    """用 payloads({'chara': b64 ASCII 字节, 'ccv3': ...}) 替换 PNG 中所有旧 chara/ccv3 块。

    新块写在第一个旧块的位置；没有旧块时紧跟 IHDR。缺 IEND 时补一个。
    """
    sig, chunks, trailing = parse_chunks(blob)
    new_raw = [_build_chunk(b"tEXt", kw.encode("latin-1") + b"\0" + payloads[kw])
               for kw in CARD_KEYWORDS if kw in payloads]
    has_old = any(_is_card_chunk(c) for c in chunks)

    parts: list[bytes] = [sig]
    inserted = False
    for ch in chunks:
        if _is_card_chunk(ch):
            if not inserted:
                parts.extend(new_raw)
                inserted = True
            continue
        parts.append(ch.raw)
        if ch.type == b"IHDR" and not has_old and not inserted:
            parts.extend(new_raw)
            inserted = True
    if not inserted:
        parts[1:1] = new_raw
    if chunks and chunks[-1].type == b"IEND":
        parts.append(trailing)
    else:
        parts.append(_build_chunk(b"IEND", b""))
    return b"".join(parts)