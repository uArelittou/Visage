from __future__ import annotations

import base64
import json

import pytest

from backend.card import CardParseError, png
from backend.card.deepscan import deep_scan_for_json
from backend.card.models import Card


def _payloads(mk, v2=None):
    return {"chara": mk.b64_json(v2 or mk.V2_CARD), "ccv3": mk.b64_json(mk.V3_CARD)}


def test_embed_inserts_after_ihdr_when_no_old_block(mk):
    base = mk.plain_png()
    out = png.embed_payloads(base, _payloads(mk))
    types = [t for t, _ in mk.split_chunks(out)]
    assert types[:4] == [b"IHDR", b"tEXt", b"tEXt", b"IDAT"] and types[-1] == b"IEND"


def test_embed_keeps_position_of_first_old_block(mk):
    old = mk.png_with(mk.plain_png(), after_idat=[mk.text_chunk("chara", mk.b64_json(mk.V2_CARD))])
    out = png.embed_payloads(old, _payloads(mk))
    types = [t for t, _ in mk.split_chunks(out)]
    assert types == [b"IHDR", b"IDAT", b"tEXt", b"tEXt", b"IEND"]


def test_embed_preserves_trailing_bytes_after_iend(mk):
    base = mk.png_with(mk.plain_png(), [mk.text_chunk("chara", mk.b64_json(mk.V2_CARD))], end=b"TRAILER-DATA")
    out = png.embed_payloads(base, _payloads(mk))
    assert out.endswith(b"TRAILER-DATA")


def test_embed_appends_iend_to_truncated_png(mk):
    full = mk.plain_png()
    cut = full[:-12]  # 去掉 IEND
    out = png.embed_payloads(cut, _payloads(mk))
    chunks = mk.split_chunks(out)
    assert chunks[-1][0] == b"IEND"
    assert png.extract_payloads(png.parse_chunks(out)[1]).keys() == {"chara", "ccv3"}


def test_embed_rejects_non_png():
    with pytest.raises(CardParseError):
        png.embed_payloads(b"GIF89a....", {})


def test_extract_skips_corrupt_first_block_and_uses_next(mk):
    blob = mk.png_with(mk.plain_png(), [mk.text_chunk("chara", b"@@@@"), mk.text_chunk("chara", mk.b64_json(mk.V2_CARD))])
    got = png.extract_payloads(png.parse_chunks(blob)[1])
    assert got["chara"]["data"]["name"] == "二号机"


def test_new_chunks_have_valid_crc(mk):
    import zlib
    out = png.embed_payloads(mk.plain_png(), _payloads(mk))
    for t, raw in mk.split_chunks(out):
        assert int.from_bytes(raw[-4:], "big") == zlib.crc32(raw[4:-4]) & 0xFFFFFFFF, t


def test_deep_scan_ignores_trailing_base64_lookalike_bytes(mk):
    payload = mk.b64_json(mk.V2_CARD)
    for junk in (b"", b"a", b"aB", b"aB9", b"aB9+", b"==Zz"):
        blob = b"\x00\x01garbage" + payload + junk + b"\x00\x00IEND"
        found = deep_scan_for_json(blob)
        assert found is not None and found["data"]["name"] == "二号机", junk


def test_deep_scan_plain_json_text_keeps_utf8(mk):
    blob = b"\xff\xfe\x00" + json.dumps(mk.V2_CARD, ensure_ascii=False).encode("utf-8") + b"\x00tail"
    found = deep_scan_for_json(blob)
    assert found["data"]["name"] == "二号机"


def test_deep_scan_nothing_found():
    assert deep_scan_for_json(b"\x00" * 1000) is None
    assert deep_scan_for_json(base64.b64encode(b'{"foo": 1}')) is None  # 不是卡


def test_empty_card_to_dicts():
    c = Card()
    v2, v3 = c.to_v2_dict(), c.to_v3_dict()
    assert v2["spec"] == "chara_card_v2" and v3["spec"] == "chara_card_v3"
    assert v2["data"]["extensions"] == {} and "character_book" not in v2["data"]
    assert v3["data"]["group_only_greetings"] == []
    assert list(v2)[:2] == ["spec", "spec_version"]


def test_to_dicts_do_not_mutate_card(mk):
    c = Card.from_dict(mk.deep(mk.V2_CARD))
    snapshot = json.dumps(c.raw, sort_keys=True)
    d = c.to_v3_dict()
    d["data"]["extensions"]["injected"] = 1
    d["data"]["alternate_greetings"].append("x")
    assert json.dumps(c.raw, sort_keys=True) == snapshot
    assert "injected" not in c.extensions and c.alternate_greetings == ["问候一", "问候二"]
