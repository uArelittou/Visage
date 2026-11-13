"""图片/损坏文件的深度扫描：从任意二进制里捞出内嵌的角色卡 JSON（移植自参考项目 pngParser.js）。"""
from __future__ import annotations

import base64
import binascii
import json
import re

_B64_RE = re.compile(r"eyJ[A-Za-z0-9+/=]+")  # 'eyJ' 是 '{"' 的 Base64 前缀
_HEAD_WINDOW = 1024 * 1024
_HEAD_CAP = 500 * 1024
_FULL_CAP = 8 * 1024 * 1024


def decode_base64_json(text: bytes | str) -> object:
    """Base64(UTF-8 JSON) 或直接的 JSON 文本 -> Python 对象。失败抛 ValueError。"""
    if isinstance(text, str):
        text = text.encode("latin-1", "ignore")
    s = text.replace(b"\0", b"").strip()
    if s[:1] in (b"{", b"["):
        payload = s
    else:
        s = re.sub(rb"\s+", b"", s)
        s += b"=" * (-len(s) % 4)
        try:
            payload = base64.b64decode(s)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"Base64 解码失败: {e}") from e
    try:
        text_out = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        # 参考项目 TextDecoder(fatal:false) 的行为：坏字节替换为 U+FFFD 而不是整体放弃
        text_out = payload.decode("utf-8", errors="replace")
    return json.loads(text_out)


def _is_cardish_b64(obj: object) -> bool:
    if not isinstance(obj, dict):
        return False
    data = obj.get("data")
    return bool(obj.get("name") or (isinstance(data, dict) and data.get("name")))


def _scan_plain_json(blob: bytes, cap: int) -> dict | None:
    idx = blob.find(b'"name"')
    if idx == -1:
        return None
    # 与参考项目的花括号配平不同：用 raw_decode 正确处理字符串里的花括号，且按 UTF-8 解码避免中文变乱码。
    # 最近的 '{' 往往只是 data 子对象；继续向外找到带 spec/data 的外层对象，找不到才退回最内层。
    innermost: dict | None = None
    end = idx
    for _ in range(8):
        start = blob.rfind(b"{", 0, end)
        if start == -1:
            break
        end = start
        text = blob[start:start + cap].decode("utf-8", errors="replace")
        try:
            obj, consumed = json.JSONDecoder().raw_decode(text)
        except ValueError:
            continue
        if not isinstance(obj, dict) or len(text[:consumed].encode("utf-8", "replace")) + start <= idx:
            continue
        if "spec" in obj or isinstance(obj.get("data"), dict):
            return obj
        if innermost is None and (obj.get("name") or obj.get("data")):
            innermost = obj
    return innermost

def deep_scan_for_json(blob: bytes) -> dict | None:
    """先找 Base64 块（最长优先），再找裸 JSON 文本。找不到返回 None。"""
    text = blob.decode("latin-1")
    candidates = sorted(_B64_RE.findall(text), key=len, reverse=True)
    for cand in candidates:
        # 正则会把块后面 CRC/相邻块里恰好落在 Base64 字母表内的字节也吞进来，逐字符回退几次
        for cut in range(5):
            try:
                obj = decode_base64_json(cand[:len(cand) - cut])
            except ValueError:
                continue
            if _is_cardish_b64(obj):
                return obj  # type: ignore[return-value]

    found = _scan_plain_json(blob[:_HEAD_WINDOW], _HEAD_CAP)
    if found is None and len(blob) > _HEAD_WINDOW:
        found = _scan_plain_json(blob, _FULL_CAP)
    return found
