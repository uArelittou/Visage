"""样例卡生成器：只用标准库 + Pillow 手工拼 PNG 块，刻意不依赖 backend.card，避免用被测代码造数据。"""
from __future__ import annotations

import base64
import copy
import io
import json
import struct
import zlib
from pathlib import Path

from PIL import Image

SIG = b"\x89PNG\r\n\x1a\n"

# ------------------------------------------------------------------ 样例卡数据
V1_CARD = {
    "name": "老派V1",
    "description": "V1 描述",
    "personality": "沉稳",
    "scenario": "酒馆",
    "first_mes": "你好，旅人。",
    "mes_example": "<START>\n{{user}}: hi\n{{char}}: hello",
    "create_date": "2024-1-1 @00h 00m 00s",
    "talkativeness": "0.5",
}

V2_CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "unknown_root_key": {"keep": [1, 2, 3]},
    "data": {
        "name": "二号机",
        "description": "V2 描述",
        "personality": "冷静",
        "scenario": "实验室",
        "first_mes": "启动完毕。",
        "mes_example": "",
        "creator_notes": "作者备注",
        "system_prompt": "你是二号机",
        "post_history_instructions": "保持角色",
        "alternate_greetings": ["问候一", "问候二"],
        "tags": ["科幻", "机器人"],
        "creator": "tester",
        "character_version": "1.2",
        "x_unknown_field": {"a": [1, {"b": None}], "c": "中文"},
        "character_book": {
            "name": "内嵌书",
            "extensions": {},
            "entries": [
                {"keys": ["k1"], "content": "词条内容", "extensions": {}, "enabled": True,
                 "insertion_order": 0, "uid": 7, "_filename": "keep.me"},
            ],
        },
        "extensions": {
            "talkativeness": "0.7",
            "regex_scripts": [
                {"id": "r1", "scriptName": "去括号", "findRegex": "/\\(.*?\\)/g", "replaceString": ""},
            ],
            "tavern_helper": {
                "scripts": [{"type": "script", "enabled": True, "name": "助手脚本", "id": "s1",
                             "content": "console.log('hi')"}],
                "variables": {"hp": 100},
            },
            "my_custom_plugin": {"deep": {"x": [1, 2, {"y": None}]}, "flag": True, "num": 1.5},
        },
    },
}

V3_CARD = {
    "spec": "chara_card_v3",
    "spec_version": "3.0",
    "data": {
        "name": "三号",
        "description": "V3 描述",
        "personality": "",
        "scenario": "",
        "first_mes": "v3 开场",
        "mes_example": "",
        "creator_notes": "v3 备注",
        "system_prompt": "",
        "post_history_instructions": "",
        "alternate_greetings": [],
        "tags": ["v3"],
        "creator": "tester",
        "character_version": "3",
        "group_only_greetings": ["群聊问候"],
        "nickname": "小三",
        "creator_notes_multilingual": {"zh": "中文备注", "en": "english"},
        "source": ["https://example.invalid/card"],
        "assets": [{"type": "icon", "uri": "ccdefault:", "name": "main", "ext": "png"}],
        "creation_date": 1700000000,
        "modification_date": 1700000001,
        "extensions": {
            "TavernHelper_scripts": [
                {"type": "script", "value": {"id": "legacy1", "name": "旧版脚本", "content": "x=1"}},
            ],
            "unknown_ext": {"keep": "me"},
        },
    },
}

CJK_CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "モンスター娘🐉",
        "description": "中文、日本語、한국어、emoji 😀👨‍👩‍👧‍👦🏳️‍🌈、Ünïcödé、\U0001F680 与 \"引号\" \\ 反斜杠\n换行",
        "personality": "",
        "scenario": "",
        "first_mes": "你好呀 (｡･ω･｡)ﾉ♡",
        "mes_example": "",
        "creator_notes": "",
        "system_prompt": "",
        "post_history_instructions": "",
        "alternate_greetings": ["こんにちは🌸"],
        "tags": ["中文标签", "🏷️"],
        "creator": "作者🙂",
        "character_version": "",
        "extensions": {"备注": {"键🔑": "值✅"}},
    },
}


def deep(obj):
    return copy.deepcopy(obj)


# ------------------------------------------------------------------ PNG 工具
def chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def split_chunks(png: bytes) -> list[tuple[bytes, bytes]]:
    """[(type, raw_chunk_bytes)]，仅用于造数据与测试断言。"""
    assert png[:8] == SIG
    out, off = [], 8
    while off + 12 <= len(png):
        (n,) = struct.unpack_from(">I", png, off)
        out.append((png[off + 4:off + 8], png[off:off + 12 + n]))
        off += 12 + n
    return out


def assemble(raws: list[bytes]) -> bytes:
    return SIG + b"".join(raws)


def b64_json(obj) -> bytes:
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def text_chunk(keyword: str, payload: bytes) -> bytes:
    return chunk(b"tEXt", keyword.encode("latin-1") + b"\0" + payload)


def itxt_chunk(keyword: str, payload: bytes, compressed: bool = False, lang: str = "zh", trans: str = "译名") -> bytes:
    body = zlib.compress(payload) if compressed else payload
    data = (keyword.encode("latin-1") + b"\0" + bytes([1 if compressed else 0, 0])
            + lang.encode() + b"\0" + trans.encode("utf-8") + b"\0" + body)
    return chunk(b"iTXt", data)


def plain_png(width: int = 24, height: int = 16, seed: int = 0) -> bytes:
    im = Image.new("RGBA", (width, height))
    px = im.load()
    for x in range(width):
        for y in range(height):
            px[x, y] = ((x * 10 + seed) % 256, (y * 15) % 256, (x * y + seed) % 256, 255)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def png_with(base: bytes, before_idat: list[bytes] = (), after_idat: list[bytes] = (), end: bytes | None = None) -> bytes:
    """在 IHDR 之后、第一个 IDAT 之前插入 before_idat；在 IEND 之前插入 after_idat。"""
    raws = []
    ch = split_chunks(base)
    ihdr_done = False
    for t, raw in ch:
        if t == b"IEND":
            raws.extend(after_idat)
        raws.append(raw)
        if t == b"IHDR" and not ihdr_done:
            raws.extend(before_idat)
            ihdr_done = True
    return assemble(raws) + (end or b"")


def card_png(card: dict, keyword: str = "chara", seed: int = 0, extra: bool = False) -> bytes:
    before = [text_chunk(keyword, b64_json(card))]
    after = []
    if extra:
        before = [chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
                  text_chunk("Software", b"fixture-generator"),
                  chunk(b"prVt", b"\x00\x01\x02private-bytes\xff")] + before
        after = [text_chunk("Comment", "尾部注释 after IDAT".encode("utf-8"))]
    return png_with(plain_png(seed=seed), before, after)


def webp_card(card: dict) -> bytes:
    im = Image.new("RGB", (20, 12), (200, 80, 40))
    buf = io.BytesIO()
    im.save(buf, "WEBP", lossless=True, xmp=b"<x:xmpmeta>chara=" + b64_json(card) + b"</x:xmpmeta>")
    return buf.getvalue()


# ------------------------------------------------------------------ 批量生成
def make_all(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    j = lambda o: json.dumps(o, ensure_ascii=False, indent=2).encode("utf-8")

    files["v1.json"] = j(V1_CARD)
    files["v2.json"] = j(V2_CARD)
    files["v3.json"] = j(V3_CARD)
    files["v1.png"] = card_png(V1_CARD)
    files["v2.png"] = card_png(V2_CARD)
    files["v3.png"] = card_png(V3_CARD, keyword="ccv3")
    files["cjk.png"] = card_png(CJK_CARD)
    files["cjk.json"] = j(CJK_CARD)
    files["extras.png"] = card_png(V2_CARD, extra=True, seed=3)

    # ccv3 与 chara 同时存在且内容不同：chara 在前，必须读到 ccv3
    old_v2, new_v3 = deep(V2_CARD), deep(V3_CARD)
    old_v2["data"]["name"] = "旧chara"
    new_v3["data"]["name"] = "新ccv3"
    files["both.png"] = png_with(plain_png(), [text_chunk("chara", b64_json(old_v2)), text_chunk("ccv3", b64_json(new_v3))])

    files["itxt.png"] = png_with(plain_png(), [itxt_chunk("chara", b64_json(V2_CARD))])
    files["itxt_zlib.png"] = png_with(plain_png(), [itxt_chunk("ccv3", b64_json(V3_CARD), compressed=True)])

    hybrid = deep(V2_CARD)
    for k in ("name", "description", "personality", "scenario", "first_mes", "mes_example"):
        hybrid[k] = hybrid["data"][k]
    hybrid["avatar"] = "none"
    files["hybrid.json"] = j(hybrid)

    # 前面有一个声称超长的坏块，标准块解析会中断，必须靠深度扫描救回
    broken = SIG + chunk(b"IHDR", plain_png()[16:29]) + struct.pack(">I", 0x7FFFFFFF) + b"junK" + b"\0" * 8 \
        + text_chunk("chara", b64_json(V2_CARD)) + chunk(b"IEND", b"")
    files["damaged.png"] = broken

    files["v2.webp"] = webp_card(V2_CARD)

    # ---- 坏文件
    files["bad_garbage.png"] = SIG + bytes(range(7, 200))
    files["bad_empty.png"] = b""
    files["bad_notpng.png"] = b"this is not an image at all"
    files["bad_text.json"] = "这不是 JSON {".encode("utf-8")
    files["bad_array.json"] = b"[1, 2, 3]"
    files["bad_worldbook.json"] = j({"name": "某世界书", "entries": {"0": {"keys": ["a"], "content": "b"}}})
    files["bad_chat.json"] = j({"name": "chat", "messages": [], "chat_metadata": {}})
    files["bad_nocard.png"] = plain_png()
    full = card_png(V2_CARD)
    files["bad_truncated.png"] = full[:60]  # 截在 chara 块中间
    files["bad_b64.png"] = png_with(plain_png(), [text_chunk("chara", b"!!!not-base64!!!")])
    files["bad_unknown_spec.json"] = j({"spec": "chara_card_v9", "data": {"name": "x"}})

    paths = {}
    for name, blob in files.items():
        p = out_dir / name
        p.write_bytes(blob)
        paths[name] = p
    return paths
