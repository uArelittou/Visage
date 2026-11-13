from rating_helpers import lore, make_card

from backend.rating.blocks import card_blocks
from backend.rating.stats import compile_js_regex, compute_stats, html_chars


def test_mofa_expected_numbers(mofa):
    s = mofa.stats
    assert s["greeting_count"] == 2
    assert [g["chars"] for g in s["greeting_lengths"]] == [2232, 1749]
    assert [g["length_score"] for g in s["greeting_lengths"]] == [2, 1]
    assert s["lorebook_entry_counts"] == {
        "total": 31, "enabled": 29, "constant": 16, "selective": 13, "disabled": 2,
    }
    assert s["constant_total_chars"]["total"] == 33731
    assert len(s["constant_total_chars"]["per_entry"]) == 16
    assert s["dead_entries"] == []
    assert s["selective_keys_not_mentioned"] == []
    assert s["keyword_collisions"] == []
    assert s["duplicate_paragraphs"] == []
    assert {e["name"] for e in s["mvu_closed_entries"]} == {"[initvar]变量初始化", "[mvu_update]变量输出格式强调"}
    assert len(s["regex_compile"]) == 7 and all(r["compiles"] for r in s["regex_compile"])
    r0 = s["regex_html"][0]
    assert (r0["html_chars"], r0["scope"], r0["sent_to_model"]) == (25868, "仅显示", False)
    assert all(not r["sent_to_model"] for r in s["regex_html"] if r["scope"] == "仅显示")
    assert s["html_in_prompt"] == []
    assert s["program_not_applicable"] == []


def test_linxiaoye_expected_numbers(lin):
    s = lin.stats
    assert s["greeting_count"] == 5
    assert [g["chars"] for g in s["greeting_lengths"]] == [2567, 2825, 2573, 2595, 2608]
    assert s["lorebook_entry_counts"] == {
        "total": 7, "enabled": 7, "constant": 6, "selective": 1, "disabled": 0,
    }
    assert s["constant_total_chars"]["total"] == 4304
    assert s["dead_entries"] == []
    assert s["regex_compile"] == [] and s["regex_html"] == []


def test_block_labels_unique_and_ordered(mofa):
    labels = [b.location for b in mofa.blocks]
    assert len(labels) == len(set(labels))
    assert labels.index("开场白#0") < labels.index("开场白#1") < next(
        i for i, x in enumerate(labels) if x.startswith("世界书#"))
    assert labels[-1].startswith("脚本#") or labels[-1].startswith("正则#")


def test_semantic_tags_are_not_html():
    text = "<核心规则>\n<JSONPatch>x</JSONPatch>\n<status_current_variables>a</status_current_variables>"
    assert html_chars(text) == 0
    assert html_chars("<div class='a'>x</div><br/>") == len("<div class='a'>") + len("</div>") + len("<br/>")
    assert html_chars("<style>a{}</style>") == len("<style>a{}</style>")
    assert html_chars("```html\n<p>x</p>\n```") == len("```html\n<p>x</p>\n```")


def test_greeting_length_strips_variable_blocks_and_hidden_regex():
    body = "你好，世界。" * 10  # 60 字
    first = f"{body}\n<UpdateVariable>x</UpdateVariable>\n[initvar]y[/initvar]\n<div>  </div>\n```js\nzz\n```\n隐藏块"
    card = make_card(
        first_mes=first,
        extensions={"regex_scripts": [
            {"scriptName": "隐藏", "findRegex": "/隐藏块/", "replaceString": "", "markdownOnly": True},
            {"scriptName": "关闭的", "findRegex": "/你好/", "replaceString": "", "markdownOnly": True, "disabled": True},
        ]},
    )
    assert compute_stats(card)["greeting_lengths"][0]["chars"] == 60


def test_empty_greetings_not_counted_and_indexed_densely():
    card = make_card(first_mes="  ", alternate_greetings=["", "甲" * 10, "  \n", "乙" * 10])
    s = compute_stats(card)
    assert s["greeting_count"] == 2
    assert [g["location"] for g in s["greeting_lengths"]] == ["开场白#0", "开场白#1"]
    assert "opening" not in s["program_not_applicable"]
    assert "opening" in compute_stats(make_card(first_mes=""))["program_not_applicable"]


def test_lorebook_dead_closed_collisions_and_unmentioned():
    entries = [
        lore(1, "总览" * 20, constant=True, name="总览"),
        lore(2, "关了", enabled=False, name="废条目"),
        lore(3, "mvu", enabled=False, name="[initvar]变量初始化"),
        lore(4, "无词", name="无关键词的绿灯"),
        lore(5, "甲", keys=["艾琳", "Aileen"], name="艾琳"),
        lore(6, "乙", keys=["aileen"], name="撞车"),
        lore(7, "丙", keys=["从未提及的词"], name="没人提到"),
    ]
    card = make_card(first_mes="开场里有艾琳。", character_book={"entries": entries})
    s = compute_stats(card)
    assert s["lorebook_entry_counts"] == {"total": 7, "enabled": 5, "constant": 1, "selective": 4, "disabled": 2}
    assert {(d["location"], d["why"]) for d in s["dead_entries"]} == {
        ("世界书#2", "条目关闭"), ("世界书#4", "绿灯无关键词"),
    }
    assert [e["location"] for e in s["mvu_closed_entries"]] == ["世界书#3"]
    assert len(s["keyword_collisions"]) == 1
    assert sorted(s["keyword_collisions"][0]["locations"]) == ["世界书#5", "世界书#6"]
    assert [e["location"] for e in s["selective_keys_not_mentioned"]] == ["世界书#6", "世界书#7"]


def test_no_enabled_lorebook_marks_program_na():
    card = make_card(first_mes="x" * 5, character_book={"entries": [lore(1, enabled=False)]})
    na = compute_stats(card)["program_not_applicable"]
    assert {"lorebook_structure", "lorebook_placement"} <= set(na)


def test_duplicate_paragraph_needs_40_chars_and_ignores_disabled():
    para = "这是一段需要足够长才会被判为重复的设定文字，长度超过四十个字符，用来测试重复段落的统计口径。再补一点。"
    assert len(para) >= 40
    card = make_card(
        first_mes=para + "\n短句",
        description=para,
        character_book={"entries": [
            lore(1, para + "\n另一行", constant=True),
            lore(2, para, enabled=False),
        ]},
    )
    dups = compute_stats(card)["duplicate_paragraphs"]
    assert len(dups) == 1
    assert dups[0]["occurrences"] == 3
    assert set(dups[0]["locations"]) == {"开场白#0", "字段:description", "世界书#1"}
    assert compute_stats(make_card(first_mes="短" * 30 + "\n" + "短" * 30))["duplicate_paragraphs"] == []


def test_regex_compile_failure_and_scope():
    card = make_card(first_mes="x" * 5, extensions={"regex_scripts": [
        {"scriptName": "坏", "findRegex": "/(unclosed/", "replaceString": "", "markdownOnly": True},
        {"scriptName": "命名组", "findRegex": "/(?<n>a)\\k<n>/g", "replaceString": "<div>x</div>", "promptOnly": True},
        {"scriptName": "改写", "findRegex": "/a/", "replaceString": "<b>x</b>"},
        {"scriptName": "Unicode", "findRegex": "/\\p{L}+/u", "replaceString": "", "markdownOnly": True},
        {"scriptName": "关闭", "findRegex": "/a/", "replaceString": "<b>x</b>", "disabled": True},
    ]})
    s = compute_stats(card)
    assert [r["compiles"] for r in s["regex_compile"]] == [False, True, True, True, True]
    assert s["regex_compile"][0]["error"]
    assert [r["scope"] for r in s["regex_html"]] == ["仅显示", "仅发送", "改写原文", "仅显示", "改写原文"]
    assert [r["sent_to_model"] for r in s["regex_html"]] == [False, True, True, False, False]
    assert compile_js_regex("/a.b/s").search("a\nb")


def test_prompt_only_regex_removes_html_before_counting():
    html = "<div>" + "x" * 3100 + "</div>"
    card = make_card(first_mes=html, extensions={"regex_scripts": [
        {"scriptName": "给上下文瘦身", "findRegex": "/<div>[\\s\\S]*<\\/div>/", "replaceString": "", "promptOnly": True},
    ]})
    assert compute_stats(card)["html_in_prompt"] == []
    plain = make_card(first_mes=html)
    assert compute_stats(plain)["html_in_prompt"] == [{"location": "开场白#0", "html_chars": 11}]
    assert card_blocks(card)[0].location == "开场白#0"


def test_greeting_chars_keep_text_rendered_by_earlier_display_regex():
    """先渲染再兜底删除的两条同查找正则，正文不能被算成 0 字。"""
    from backend.rating.stats import _display_strippers, greeting_body_chars

    class C:
        regex_scripts = [
            {"markdownOnly": True, "findRegex": r"<game_text>([\s\S]*?)<\/game_text>", "replaceString": "<div>$1</div>"},
            {"markdownOnly": True, "findRegex": r"<game_text>([\s\S]*?)<\/game_text>", "replaceString": ""},
        ]

    s = _display_strippers(C())
    assert greeting_body_chars("<game_text>雨还在下</game_text>", s) == 4
    assert greeting_body_chars("<game_text>雨还在下</game_text>", s[1:]) == 0
