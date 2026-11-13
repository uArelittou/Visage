from __future__ import annotations

import io
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from backend.card import Card, CardParseError, CardWriteError, load_card, read_image_bytes, save_card
from backend.card import fsio


def _non_card_chunks(mk, blob: bytes) -> list[bytes]:
    out = []
    for t, raw in mk.split_chunks(blob):
        if t in (b"tEXt", b"iTXt", b"zTXt") and raw[8:].split(b"\0", 1)[0] in (b"chara", b"ccv3"):
            continue
        out.append(raw)
    return out


def _card_chunks(mk, blob: bytes) -> list[tuple[str, dict]]:
    import base64
    res = []
    for t, raw in mk.split_chunks(blob):
        if t == b"tEXt":
            kw, _, payload = raw[8:-4].partition(b"\0")
            if kw in (b"chara", b"ccv3"):
                res.append((kw.decode(), json.loads(base64.b64decode(payload).decode("utf-8"))))
    return res


def _pixels(blob: bytes):
    with Image.open(io.BytesIO(blob)) as im:
        return im.size, im.mode, im.tobytes()


def _data_layer(raw: dict) -> dict:
    return raw["data"] if isinstance(raw.get("data"), dict) else raw


def _same_content(a: Card, b: Card) -> bool:
    """除 spec 外全部字段一致。V2 卡写回后带 ccv3，读回时 spec 会变成 V3，这是预期行为。"""
    return replace(a, spec="") == replace(b, spec="")


# ---------------------------------------------------------------- PNG 往返
@pytest.mark.parametrize("name", ["v2.png", "extras.png", "cjk.png", "itxt.png", "v3.png", "both.png", "damaged.png"])
def test_png_roundtrip_card_equal(work, name):
    p = work(name)
    before = load_card(p)
    save_card(p, before)
    after = load_card(p)
    assert _same_content(after, before)
    assert after.spec == "chara_card_v3"


def test_png_roundtrip_v3_raw_identical(work):
    p = work("v3.png")
    before = load_card(p)
    save_card(p, before)
    after = load_card(p)
    assert after.spec == "chara_card_v3"
    assert after.raw == before.raw


def test_png_roundtrip_v2_data_layer_preserved(work):
    p = work("v2.png")
    before = load_card(p)
    save_card(p, before)
    after = load_card(p)
    b, a = _data_layer(before.raw), _data_layer(after.raw)
    for k, v in b.items():
        assert a[k] == v, k
    assert after.raw["unknown_root_key"] == before.raw["unknown_root_key"]
    assert after.raw["data"]["x_unknown_field"] == {"a": [1, {"b": None}], "c": "中文"}
    assert after.extensions["my_custom_plugin"] == before.extensions["my_custom_plugin"]
    assert after.character_book["entries"][0]["_filename"] == "keep.me"


def test_png_writes_both_chara_v2_and_ccv3_v3(mk, work):
    p = work("v2.png")
    save_card(p, load_card(p))
    chunks = _card_chunks(mk, p.read_bytes())
    assert [k for k, _ in chunks] == ["chara", "ccv3"]
    spec = dict(chunks)
    assert spec["chara"]["spec"] == "chara_card_v2" and spec["chara"]["spec_version"] == "2.0"
    assert spec["ccv3"]["spec"] == "chara_card_v3" and spec["ccv3"]["spec_version"] == "3.0"
    assert spec["ccv3"]["data"]["group_only_greetings"] == []


def test_png_non_text_chunks_byte_identical(mk, work, cards):
    p = work("extras.png")
    original = p.read_bytes()
    save_card(p, load_card(p))
    new = p.read_bytes()
    assert _non_card_chunks(mk, new) == _non_card_chunks(mk, original)
    # extras.png 里 Software / Comment 等非卡文本块也必须保留
    assert b"fixture-generator" in new and "尾部注释".encode() in new
    assert _pixels(new) == _pixels(original)


def test_png_replaces_old_blocks_no_ghost(mk, work):
    p = work("both.png")  # 原本 chara(旧) + ccv3(新)
    card = load_card(p)
    card.name = "改名了"
    save_card(p, card)
    chunks = _card_chunks(mk, p.read_bytes())
    assert [k for k, _ in chunks] == ["chara", "ccv3"]
    assert all(d["data"]["name"] == "改名了" for _, d in chunks)
    assert load_card(p).name == "改名了"


def test_png_itxt_replaced_by_text_chunks(mk, work):
    p = work("itxt.png")
    save_card(p, load_card(p))
    types = [t for t, _ in mk.split_chunks(p.read_bytes())]
    assert b"iTXt" not in types and types.count(b"tEXt") == 2


def test_edit_persists(work):
    p = work("v2.png")
    c = load_card(p)
    c.description = "改写后的描述 ✏️"
    c.tags = c.tags + ["新标签"]
    c.extensions["added"] = {"k": "v"}
    c.character_book = None
    save_card(p, c)
    d = load_card(p)
    assert d.description == "改写后的描述 ✏️"
    assert d.tags[-1] == "新标签"
    assert d.extensions["added"] == {"k": "v"}
    assert d.extensions["my_custom_plugin"]["flag"] is True
    assert d.character_book is None


def test_cjk_emoji_survive_png(work, mk):
    p = work("cjk.png")
    save_card(p, load_card(p))
    c = load_card(p)
    assert c.name == "モンスター娘🐉"
    assert c.description == mk.CJK_CARD["data"]["description"]


def test_v1_png_upgraded_to_v2_on_save(mk, work):
    p = work("v1.png")
    before = load_card(p)
    save_card(p, before)
    chara = dict(_card_chunks(mk, p.read_bytes()))["chara"]
    assert chara["spec"] == "chara_card_v2"
    assert chara["data"]["name"] == "老派V1"
    assert chara["data"]["create_date"] == "2024-1-1 @00h 00m 00s"  # V1 未知键进入 data，不丢
    assert load_card(p).name == "老派V1"


# ---------------------------------------------------------------- 换封面
def _jpeg_bytes(size=(40, 30), color=(10, 200, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def test_replace_cover_with_png_keeps_data(work, mk):
    p = work("extras.png")
    before = load_card(p)
    new_png = mk.plain_png(width=48, height=40, seed=9)
    save_card(p, before, image_bytes=new_png)
    after = load_card(p)
    assert _same_content(after, before)
    assert _pixels(p.read_bytes()) == _pixels(new_png)
    assert read_image_bytes(p) is not None


def test_replace_cover_with_jpeg_converts_to_png(work):
    p = work("v2.png")
    before = load_card(p)
    save_card(p, before, image_bytes=_jpeg_bytes())
    blob = p.read_bytes()
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    assert _pixels(blob)[0] == (40, 30)
    assert _same_content(load_card(p), before)


def test_replace_cover_drops_old_card_blocks_from_new_image(work, mk):
    p = work("v2.png")
    card = load_card(p)
    stale = mk.card_png(mk.V3_CARD, keyword="ccv3")  # 新封面自带另一张卡的数据，必须被覆盖
    save_card(p, card, image_bytes=stale)
    names = [d["data"]["name"] for _, d in _card_chunks(mk, p.read_bytes())]
    assert names == ["二号机", "二号机"]


def test_replace_cover_bad_image_raises_and_keeps_file(work):
    p = work("v2.png")
    original = p.read_bytes()
    with pytest.raises(CardParseError):
        save_card(p, load_card(p), image_bytes=b"not an image")
    assert p.read_bytes() == original


# ---------------------------------------------------------------- JSON
def test_json_roundtrip_v2_preserves_unknown(work):
    p = work("v2.json")
    before = load_card(p)
    save_card(p, before)
    after = load_card(p)
    assert after == before and after.raw == before.raw
    text = p.read_text("utf-8")
    assert "二号机" in text and "\\u" not in text  # 中文不转义


def test_json_v3_stays_v3_and_v1_upgrades_to_v2(work):
    p3, p1 = work("v3.json"), work("v1.json")
    save_card(p3, load_card(p3))
    assert json.loads(p3.read_text("utf-8"))["spec"] == "chara_card_v3"
    save_card(p1, load_card(p1))
    d = json.loads(p1.read_text("utf-8"))
    assert d["spec"] == "chara_card_v2" and d["data"]["talkativeness"] == "0.5"


def test_hybrid_json_flat_fields_stay_in_sync(work):
    p = work("hybrid.json")
    c = load_card(p)
    c.name = "同步后的名字"
    save_card(p, c)
    d = json.loads(p.read_text("utf-8"))
    assert d["name"] == d["data"]["name"] == "同步后的名字"
    assert d["avatar"] == "none"


def test_json_with_image_upgrades_to_png(work):
    p = work("v2.json")
    card = load_card(p)
    out = save_card(p, card, image_bytes=_jpeg_bytes())
    assert out == p.with_suffix(".png") and out.exists() and not p.exists()
    assert load_card(out).name == "二号机"


def test_json_save_returns_same_path(work):
    p = work("v2.json")
    assert save_card(p, load_card(p)) == p


# ---------------------------------------------------------------- WebP
def test_webp_upgrades_to_png(work):
    p = work("v2.webp")
    card = load_card(p)
    card.description = "webp 编辑后"
    out = save_card(p, card)
    assert out == p.with_suffix(".png")
    assert not p.exists() and out.exists()
    back = load_card(out)
    assert back.description == "webp 编辑后" and back.name == "二号机"
    assert _pixels(out.read_bytes())[0] == (20, 12)


def test_webp_upgrade_refuses_to_overwrite_existing_png(work, tmp_path):
    p = work("v2.webp")
    other = tmp_path / "v2.png"
    other.write_bytes(b"someone else's card")
    with pytest.raises(CardWriteError):
        save_card(p, load_card(p))
    assert p.exists() and other.read_bytes() == b"someone else's card"


# ---------------------------------------------------------------- 原子写
def _leftovers(d: Path) -> list[str]:
    return sorted(x.name for x in d.iterdir() if x.name.endswith(".tmp"))


def test_no_temp_files_after_success(work):
    p = work("v2.png")
    save_card(p, load_card(p))
    assert _leftovers(p.parent) == []


def test_failed_replace_keeps_original_and_cleans_tmp(work, monkeypatch):
    p = work("v2.png")
    original = p.read_bytes()
    card = load_card(p)
    card.name = "不该落盘"

    def boom(src, dst):
        raise OSError("disk exploded")

    monkeypatch.setattr(fsio.os, "replace", boom)
    with pytest.raises(OSError):
        save_card(p, card)
    assert p.read_bytes() == original
    assert _leftovers(p.parent) == []


def test_replace_retries_on_permission_error(work, monkeypatch):
    p = work("v2.json")
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("locked")
        return real(src, dst)

    monkeypatch.setattr(fsio.os, "replace", flaky)
    card = load_card(p)
    card.name = "重试成功"
    save_card(p, card)
    assert calls["n"] == 3 and load_card(p).name == "重试成功"


def test_unsupported_extension_on_save(tmp_path):
    with pytest.raises(CardParseError):
        save_card(tmp_path / "x.jpg", Card(name="x"))


def test_save_new_json_without_existing_file(tmp_path):
    p = tmp_path / "new.json"
    save_card(p, Card(name="全新", description="d"))
    assert load_card(p).name == "全新"


def test_save_png_that_does_not_exist_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        save_card(tmp_path / "ghost.png", Card(name="x"))
