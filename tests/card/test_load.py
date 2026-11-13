from __future__ import annotations

import pytest

from backend.card import Card, CardParseError, load_card, read_image_bytes


# ---------------------------------------------------------------- V1 / V2 / V3
@pytest.mark.parametrize("name", ["v1.json", "v1.png"])
def test_read_v1(cards, mk, name):
    c = load_card(cards[name])
    assert c.spec == "chara_card_v1"
    assert (c.name, c.description, c.personality) == ("老派V1", "V1 描述", "沉稳")
    assert c.first_mes == "你好，旅人。"
    assert c.creator == "" and c.tags == [] and c.alternate_greetings == []
    assert c.extensions == {} and c.character_book is None
    assert c.raw["create_date"] == mk.V1_CARD["create_date"]  # 未知字段留在 raw


@pytest.mark.parametrize("name", ["v2.json", "v2.png", "extras.png", "itxt.png", "damaged.png"])
def test_read_v2(cards, mk, name):
    c = load_card(cards[name])
    d = mk.V2_CARD["data"]
    assert c.spec == "chara_card_v2"
    assert c.name == "二号机"
    assert c.alternate_greetings == d["alternate_greetings"]
    assert c.tags == d["tags"]
    assert c.system_prompt == "你是二号机"
    assert c.post_history_instructions == "保持角色"
    assert c.creator == "tester" and c.character_version == "1.2"
    assert c.character_book["entries"][0]["content"] == "词条内容"
    assert c.extensions["my_custom_plugin"] == d["extensions"]["my_custom_plugin"]
    assert c.raw["data"]["x_unknown_field"] == d["x_unknown_field"]
    assert c.raw["unknown_root_key"] == {"keep": [1, 2, 3]}


@pytest.mark.parametrize("name", ["v3.json", "v3.png", "itxt_zlib.png"])
def test_read_v3(cards, mk, name):
    c = load_card(cards[name])
    assert c.spec == "chara_card_v3"
    assert c.name == "三号"
    assert c.raw["data"]["group_only_greetings"] == ["群聊问候"]
    assert c.raw["data"]["creator_notes_multilingual"]["zh"] == "中文备注"


def test_ccv3_takes_priority_over_chara(cards):
    c = load_card(cards["both.png"])
    assert c.spec == "chara_card_v3"
    assert c.name == "新ccv3"


def test_hybrid_json_reads_data_layer(cards):
    c = load_card(cards["hybrid.json"])
    assert c.spec == "chara_card_v2" and c.name == "二号机"


def test_cjk_and_emoji(cards, mk):
    d = mk.CJK_CARD["data"]
    for name in ("cjk.png", "cjk.json"):
        c = load_card(cards[name])
        assert c.name == "モンスター娘🐉"
        assert c.description == d["description"]
        assert c.alternate_greetings == ["こんにちは🌸"]
        assert c.tags == ["中文标签", "🏷️"]
        assert c.extensions == {"备注": {"键🔑": "值✅"}}


def test_webp_read(cards):
    c = load_card(cards["v2.webp"])
    assert c.name == "二号机" and c.spec == "chara_card_v2"


# ---------------------------------------------------------------- 脚本属性
def test_regex_scripts_and_helper_scripts(cards):
    c = load_card(cards["v2.json"])
    assert [r["scriptName"] for r in c.regex_scripts] == ["去括号"]
    assert [s["name"] for s in c.scripts] == ["助手脚本"]


def test_legacy_value_wrapped_scripts_are_unwrapped(cards):
    c = load_card(cards["v3.json"])
    assert [s["name"] for s in c.scripts] == ["旧版脚本"]
    assert c.regex_scripts == []


def test_scripts_container_shapes():
    c = Card(extensions={"tavern_helper": [["scripts", [{"name": "p", "content": "1"}]], ["variables", {}]]})
    assert [s["name"] for s in c.scripts] == ["p"]
    c = Card(extensions={"tavern_helper": {"scripts": [{"type": "folder", "name": "f",
                                                        "scripts": [{"type": "script", "name": "inner"}]}]}})
    assert [s["name"] for s in c.scripts] == ["inner"]
    assert Card().scripts == [] and Card().regex_scripts == []


# ---------------------------------------------------------------- 坏文件
@pytest.mark.parametrize("name", [
    "bad_garbage.png", "bad_empty.png", "bad_notpng.png", "bad_text.json", "bad_array.json",
    "bad_worldbook.json", "bad_chat.json", "bad_nocard.png", "bad_truncated.png", "bad_b64.png",
    "bad_unknown_spec.json",
])
def test_bad_files_raise_card_parse_error(cards, name):
    with pytest.raises(CardParseError):
        load_card(cards[name])


def test_unsupported_extension(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hello")
    with pytest.raises(CardParseError):
        load_card(p)


def test_missing_file_is_not_swallowed(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_card(tmp_path / "nope.png")


# ---------------------------------------------------------------- 封面
def test_read_image_bytes(cards):
    assert read_image_bytes(cards["v2.json"]) is None
    assert read_image_bytes(cards["v2.png"]) == cards["v2.png"].read_bytes()
    assert read_image_bytes(cards["v2.webp"]) == cards["v2.webp"].read_bytes()
    with pytest.raises(CardParseError):
        read_image_bytes(cards["bad_notpng.png"])
