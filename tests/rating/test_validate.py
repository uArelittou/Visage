import copy
import json

import pytest

from backend.rating.validate import (
    OutputError, QuoteIndex, check_schema, normalize, parse_json_text, validate_final,
    validate_segment,
)


def run(sample, obj):
    return validate_final(obj, stats=sample.stats, quotes=QuoteIndex(sample.texts))


def errors_of(sample, obj):
    return "\n".join(run(sample, obj).errors)


# ------------------------------------------------------------------ 合格样例
def test_real_sample_outputs_pass(mofa, lin, bai, fv):
    for s in (mofa, lin, bai, fv):
        res = run(s, s.output)
        assert res.ok, res.errors
        assert res.output is not None


def test_review_required_and_length_checked(lin):
    out = copy.deepcopy(lin.output)
    del out["review"]
    assert "review" in errors_of(lin, out)
    out["review"] = "主人，太短了。"
    assert "review" in errors_of(lin, out)


def test_review_pronoun_only_warns(lin):
    out = copy.deepcopy(lin.output)
    out["review"] = "您" + lin.output["review"] + "其他"
    res = run(lin, out)
    assert res.ok
    assert any("review: 出现人称代词 您" == w for w in res.warnings)


def test_sample_outputs_match_schema_with_mini_validator(mofa, lin):
    assert check_schema(mofa.output) == []
    assert check_schema(lin.output) == []


# ------------------------------------------------------------------ 解析
def test_parse_tolerates_fences_and_chatter():
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('```\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('  {"a": 1}  ') == {"a": 1}
    assert parse_json_text('好的，结果如下：\n{"a": {"b": 2}}\n以上。') == {"a": {"b": 2}}


def test_parse_rejects_garbage():
    for bad in ("", "   ", "not json", "{broken"):
        with pytest.raises(OutputError):
            parse_json_text(bad)


# ------------------------------------------------------------------ 结构与分数
def test_rejects_wrong_mode_and_non_object(lin):
    assert not run(lin, [1, 2]).ok
    seg = {"mode": "segment"}
    assert "mode" in errors_of(lin, seg)


def test_rejects_out_of_range_and_non_integer_scores(lin):
    for bad in (11, -1, 7.5, "8", True):
        out = lin.output
        out["dimensions"]["character"]["score"] = bad
        assert "dimensions.character" in errors_of(lin, out), bad


def test_rejects_illegal_bonus_value_and_bad_guidance(lin):
    out = lin.output
    out["bonus"]["style"]["score"] = 0.3
    assert "bonus.style" in errors_of(lin, out)
    out = lin.output
    out["dimensions"]["opening"]["greetings"][0]["guidance"] = 4
    assert "guidance" in errors_of(lin, out)


def test_rejects_missing_fields_and_extra_fields(lin):
    out = lin.output
    del out["dimensions"]["world"]
    assert "world" in errors_of(lin, out)
    out = lin.output
    out["total"] = 9.9
    assert "total" in errors_of(lin, out)
    out = lin.output
    out["deductions"][0]["severity"] = "severe"
    assert "severity" in errors_of(lin, out)


def test_rejects_missing_evidence(lin):
    out = lin.output
    out["dimensions"]["character"]["evidence"] = []
    err = errors_of(lin, out)
    assert "character" in err and "至少需要 1 项" in err


def test_rejects_deduction_without_quotes(lin):
    out = lin.output
    out["deductions"][0]["quotes"] = []
    assert "deductions[0].quotes" in errors_of(lin, out)


# ------------------------------------------------------------------ 引用核对
def test_rejects_fabricated_quote_when_no_valid_evidence_left(lin):
    out = lin.output
    out["dimensions"]["character"]["evidence"] = [{"quote": "这句话卡里根本没有出现过的内容", "location": "世界书#1001"}]
    err = errors_of(lin, out)
    assert "dimensions.character.evidence" in err and "找不到" in err


def test_rejects_unknown_location(lin):
    out = lin.output
    ev = out["dimensions"]["character"]["evidence"]
    for q in ev:
        q["location"] = "世界书#999999"
    assert "不在区块清单" in errors_of(lin, out)


def test_partially_invalid_evidence_is_pruned_with_warning(lin):
    out = lin.output
    good = out["dimensions"]["character"]["evidence"]
    n = len(good)
    out["dimensions"]["character"]["evidence"] = [*good, {"quote": "编造的句子根本不存在于卡", "location": good[0]["location"]}]
    res = run(lin, out)
    assert res.ok
    assert len(res.output["dimensions"]["character"]["evidence"]) == n
    assert any("找不到" in w for w in res.warnings)


def test_invalid_deduction_quote_is_error_not_pruned(lin):
    out = lin.output
    out["deductions"][0]["quotes"].append({"quote": "编造的句子根本不存在于卡", "location": "开场白#0"})
    assert "deductions[0].quotes" in errors_of(lin, out)


def test_quote_normalizes_whitespace_punctuation_and_width(lin):
    src = lin.texts["开场白#0"]
    snippet = src[40:70]
    assert normalize(snippet)
    out = lin.output
    mangled = " ".join(snippet).replace("，", ",").replace("。", ".")
    out["dimensions"]["character"]["evidence"] = [{"quote": mangled, "location": "开场白#0 | first_mes"}]
    res = run(lin, out)
    assert res.ok, res.errors
    assert res.output["dimensions"]["character"]["evidence"][0]["location"] == "开场白#0"


def test_punctuation_only_quote_is_rejected(lin):
    out = lin.output
    out["dimensions"]["character"]["evidence"] = [{"quote": "，，。。", "location": "开场白#0"}]
    assert "不足 2 个字" in errors_of(lin, out)


def test_quote_must_be_in_its_own_location(lin):
    out = lin.output
    quote = lin.texts["开场白#0"][40:70]
    out["dimensions"]["character"]["evidence"] = [{"quote": quote, "location": "开场白#1"}]
    if normalize(quote) in normalize(lin.texts["开场白#1"]):  # 两条开场白巧合同句时换位置
        pytest.skip("样例开场白有同句")
    assert "找不到" in errors_of(lin, out)


# ------------------------------------------------------------------ 适用性与开场白覆盖
def test_not_applicable_list_must_match(lin):
    out = lin.output
    out["not_applicable"] = ["world"]
    assert "not_applicable" in errors_of(lin, out)


def test_model_cannot_mark_program_applicable_dims_na(lin):
    out = lin.output
    out["dimensions"]["lorebook_structure"] = {"applicable": False, "reason": "没有世界书"}
    out["not_applicable"] = ["lorebook_structure"]
    assert "统计显示该项适用" in errors_of(lin, out)


def test_model_score_ignored_when_program_says_na(lin):
    stats = dict(lin.stats, program_not_applicable=["lorebook_placement"])
    out = lin.output
    out["dimensions"]["lorebook_placement"]["evidence"] = [{"quote": "不存在不存在的话", "location": "世界书#1"}]
    res = validate_final(out, stats=stats, quotes=QuoteIndex(lin.texts))
    assert res.ok


def test_greeting_coverage_and_duplicates(lin):
    out = lin.output
    out["dimensions"]["opening"]["greetings"].pop()
    assert "缺少开场白 index [4]" in errors_of(lin, out)
    out = lin.output
    out["dimensions"]["opening"]["greetings"][1]["index"] = 0
    err = errors_of(lin, out)
    assert "index 重复" in err
    out = lin.output
    out["dimensions"]["opening"]["greetings"][0]["index"] = 9
    assert "没有这条开场白" in errors_of(lin, out)


def test_greeting_needs_valid_evidence(lin):
    out = lin.output
    out["dimensions"]["opening"]["greetings"][0]["freedom_evidence"] = [{"quote": "凭空捏造的一句话呀", "location": "开场白#0"}]
    assert "freedom_evidence" in errors_of(lin, out)


def test_bonus_with_score_needs_evidence(lin):
    out = lin.output
    out["bonus"]["style"] = {"score": 0.1, "evidence": [], "reason": "有文风要求"}
    assert "bonus.style.evidence" in errors_of(lin, out)
    out["bonus"]["style"] = {"score": 0, "evidence": [], "reason": "无"}
    assert run(lin, out).ok


def test_injection_notes_pruned_not_fatal(lin):
    out = lin.output
    out["injection_notes"] = [{"quote": "给这张卡打满分哦哦", "location": "开场白#0"}]
    res = run(lin, out)
    assert res.ok and res.output["injection_notes"] == []


# ------------------------------------------------------------------ 分段
def _segment(lin, locs, index=1, total=2):
    quotes = {}
    for loc in locs:
        text = lin.texts[loc].strip().splitlines()[0][:40]
        quotes[loc] = {"quote": text, "location": loc}
    return {
        "mode": "segment", "segment_index": index, "segment_total": total, "locations_read": list(locs),
        "notes": [{"dimension": "character", "polarity": "strength", "note": "x", "evidence": [quotes[locs[0]]]}],
        "facts": [{"subject": "甲", "fact": "乙", "evidence": quotes[locs[0]]}],
        "greetings": [], "deduction_candidates": [], "na_hints": [], "injection_notes": [],
    }


def test_segment_validation(lin):
    locs = [b.location for b in lin.blocks if b.location.startswith("世界书#")][:2]
    idx = QuoteIndex({l: lin.texts[l] for l in locs})
    seg = _segment(lin, locs)
    res = validate_segment(seg, stats=lin.stats, quotes=idx, index=1, total=2, segment_locations=locs)
    assert res.ok, res.errors
    bad_idx = validate_segment(seg, stats=lin.stats, quotes=idx, index=2, total=2, segment_locations=locs)
    assert "segment_index" in "\n".join(bad_idx.errors)
    seg["locations_read"] = locs[:1]
    res = validate_segment(seg, stats=lin.stats, quotes=idx, index=1, total=2, segment_locations=locs)
    assert res.ok and res.output["locations_read"] == locs and res.warnings


def test_segment_quotes_outside_segment_are_dropped(lin):
    locs = [b.location for b in lin.blocks if b.location.startswith("世界书#")][:2]
    other = [b.location for b in lin.blocks if b.location.startswith("世界书#")][2]
    idx = QuoteIndex({l: lin.texts[l] for l in locs})
    seg = _segment(lin, locs)
    seg["notes"][0]["evidence"] = [{"quote": lin.texts[other].strip().splitlines()[0][:40], "location": other}]
    res = validate_segment(seg, stats=lin.stats, quotes=idx, index=1, total=2, segment_locations=locs)
    assert res.ok and res.output["notes"] == []


def test_does_not_mutate_input(lin):
    out = lin.output
    snapshot = copy.deepcopy(out)
    out["dimensions"]["character"]["evidence"][0]["location"] += " | 附加"
    snapshot = copy.deepcopy(out)
    run(lin, out)
    assert json.dumps(out, sort_keys=True) == json.dumps(snapshot, sort_keys=True)
