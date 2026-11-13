"""校验评分配置：rubric.json 数字自洽，output_schema.json 合法且与 rubric 对齐，提示词数字与 rubric 一致。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

RATING = Path(__file__).resolve().parents[1] / "backend" / "rating"
PROMPTS = RATING / "prompts"

EXPECTED_WEIGHTS = {
    "character": 19, "world": 18, "scene": 18, "lorebook_structure": 15,
    "player_space": 8, "opening": 8, "lorebook_placement": 7, "guidance": 7,
}
_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


@pytest.fixture(scope="module")
def rubric() -> dict:
    return json.loads((RATING / "rubric.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads((PROMPTS / "output_schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def system_prompt() -> str:
    return (PROMPTS / "system.md").read_text(encoding="utf-8")


def _dim_ids(rubric: dict) -> list[str]:
    return [d["id"] for d in rubric["dimensions"]]


# ------------------------------------------------------------------ rubric
def test_eight_dimensions_weights_sum_100(rubric):
    dims = rubric["dimensions"]
    assert len(dims) == 8
    assert len(set(_dim_ids(rubric))) == 8
    assert {d["id"]: d["weight"] for d in dims} == EXPECTED_WEIGHTS
    assert sum(d["weight"] for d in dims) == 100


def test_score_scale(rubric):
    assert rubric["score_scale"] == {"min": 0, "max": 10, "decimals": 1, "rounding": "half_up"}
    ds = rubric["dimension_score"]
    assert (ds["min"], ds["max"]) == (0, 10)
    assert ds["anchors"] == [0, 2, 4, 6, 8, 10]


def _check_contiguous(table: list[dict], start: int) -> None:
    expect = start
    for i, row in enumerate(table):
        assert row["min"] == expect, f"区间不连续: {row}"
        if row["max"] is None:
            assert i == len(table) - 1, "只有最后一档可以无上限"
            return
        assert row["max"] >= row["min"]
        expect = row["max"] + 1
    raise AssertionError("最后一档必须无上限")


def test_opening_tiers_match_max(rubric):
    op = rubric["opening"]
    _check_contiguous(op["count_score"], 1)
    _check_contiguous(op["length_score"], 0)
    assert [r["score"] for r in op["count_score"]] == [0, 1, 2, 3]
    assert [r["score"] for r in op["length_score"]] == [0, 1, 2, -0.5]
    # 字数档边界：<1500 / 1500~<2000 / 2000~3500 / >3500
    assert [(r["min"], r["max"]) for r in op["length_score"]] == [(0, 1499), (1500, 1999), (2000, 3500), (3501, None)]
    for key in ("guidance", "freedom"):
        part = op[key]
        assert part["values"] == list(range(part["min"], part["max"] + 1))
    assert (op["guidance"]["max"], op["freedom"]["max"]) == (3, 2)
    best = (max(r["score"] for r in op["count_score"]) + max(r["score"] for r in op["length_score"])
            + op["guidance"]["max"] + op["freedom"]["max"])
    assert best == op["max_total"] == 10
    assert op["min_total"] == 0


def test_bonus_and_deductions(rubric):
    bonus = rubric["bonus"]
    items = {b["id"]: b for b in bonus["items"]}
    assert {k: v["max"] for k, v in items.items()} == {"mvu": 0.3, "frontend": 0.3, "style": 0.2}
    for b in items.values():
        assert b["values"][0] == 0 and b["values"][-1] == b["max"]
    assert bonus["cap"] == 0.8
    assert round(sum(b["max"] for b in items.values()), 6) == bonus["cap"]

    ded = rubric["deductions"]
    assert ded["cap"] == 1.5
    assert ded["severity"] == {"light": 0.1, "medium": 0.3, "heavy": 0.6}
    assert ded["severity"]["heavy"] <= ded["per_type_cap"] <= ded["cap"]
    assert {t["id"] for t in ded["types"]} == {
        "contradiction", "duplication", "irrelevant", "nonsense", "format_error", "html_to_model",
    }


def test_na_rules(rubric):
    assert rubric["na_redistribution"]["method"] == "proportional"
    by_id = {d["id"]: d for d in rubric["dimensions"]}
    for dim_id in ("lorebook_structure", "lorebook_placement", "opening"):
        assert by_id[dim_id]["na_decided_by"] == "program"
    for d in rubric["dimensions"]:
        assert d["na_when"]


def test_precomputed_stats_listed(rubric):
    ids = {s["id"] for s in rubric["precomputed_stats"]}
    required = {
        "greeting_count", "greeting_lengths", "lorebook_entry_counts", "constant_total_chars",
        "keyword_collisions", "duplicate_paragraphs", "regex_compile", "regex_html", "mvu_closed_entries",
    }
    assert required <= ids
    for pat in rubric["lorebook_reference"]["mvu_expected_disabled_patterns"]:
        re.compile(pat)
    assert re.search(rubric["lorebook_reference"]["mvu_expected_disabled_patterns"][0], "[initvar]变量初始化勿开")


# ------------------------------------------------------------------ schema
_SUBSCHEMA_MAPS = ("properties", "$defs")
_SUBSCHEMA_LISTS = ("oneOf", "anyOf", "allOf")
_SUBSCHEMA_ONE = ("items", "not", "if", "then", "else", "additionalProperties")


def _walk_schema(node, path="#"):
    """最小元校验：不依赖 jsonschema 库，检查 type 合法、required 都在 properties，并产出 $ref。"""
    if isinstance(node, bool):
        return
    assert isinstance(node, dict), f"{path}: 子 schema 必须是对象或布尔"
    t = node.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        assert set(types) <= _SCHEMA_TYPES, f"{path}: 非法 type {t}"
    if "required" in node and "properties" in node:
        missing = set(node["required"]) - set(node["properties"])
        assert not missing, f"{path}: required 不在 properties 中 {missing}"
    if "enum" in node:
        assert isinstance(node["enum"], list) and node["enum"], f"{path}: enum 必须是非空数组"
    if "$ref" in node:
        yield node["$ref"]
    for key in _SUBSCHEMA_MAPS:
        for name, sub in node.get(key, {}).items():
            yield from _walk_schema(sub, f"{path}/{key}/{name}")
    for key in _SUBSCHEMA_LISTS:
        for i, sub in enumerate(node.get(key, [])):
            yield from _walk_schema(sub, f"{path}/{key}/{i}")
    for key in _SUBSCHEMA_ONE:
        if key in node:
            yield from _walk_schema(node[key], f"{path}/{key}")


def _resolve(schema: dict, ref: str):
    assert ref.startswith("#/"), f"只允许内部引用: {ref}"
    node = schema
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def test_schema_is_valid_json_schema(schema):
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for ref in _walk_schema(schema):
        _resolve(schema, ref)
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # 项目未依赖 jsonschema；装了就额外做官方元校验
        return
    Draft202012Validator.check_schema(schema)


def test_schema_matches_rubric(schema, rubric):
    defs = schema["$defs"]
    dim_ids = set(_dim_ids(rubric))
    final = defs["final"]
    dims = final["properties"]["dimensions"]
    assert set(dims["required"]) == dim_ids
    assert set(dims["properties"]) == dim_ids
    assert set(final["properties"]["not_applicable"]["items"]["enum"]) == dim_ids

    bonus_items = {b["id"]: b for b in rubric["bonus"]["items"]}
    bonus = final["properties"]["bonus"]
    assert set(bonus["required"]) == set(bonus["properties"]) == set(bonus_items)
    for bid, b in bonus_items.items():
        enum = bonus["properties"][bid]["allOf"][1]["properties"]["score"]["enum"]
        assert enum == b["values"]

    ded = defs["deduction"]["properties"]
    assert set(ded["type"]["enum"]) == {t["id"] for t in rubric["deductions"]["types"]}
    assert set(ded["severity"]["enum"]) == set(rubric["deductions"]["severity"])

    op = rubric["opening"]
    g = defs["greeting"]["properties"]
    assert g["guidance"]["enum"] == op["guidance"]["values"]
    assert g["freedom"]["enum"] == op["freedom"]["values"]

    sd = defs["scored_dimension"]["properties"]
    assert (sd["score"]["minimum"], sd["score"]["maximum"]) == (0, 10)
    assert sd["score"]["type"] == rubric["dimension_score"]["type"]
    assert sd["evidence"]["minItems"] == rubric["dimension_score"]["evidence_min_items"]

    seg_dims = set(defs["segment_note"]["properties"]["dimension"]["enum"])
    assert seg_dims == (dim_ids - {"opening"}) | set(bonus_items)
    assert set(defs["segment"]["properties"]["na_hints"]["items"]["properties"]["dimension"]["enum"]) == {
        d["id"] for d in rubric["dimensions"] if d["na_decided_by"] == "model"
    }


# ------------------------------------------------------------------ 提示词与 rubric 数字一致
def test_system_prompt_numbers_match_rubric(system_prompt, rubric):
    for d in rubric["dimensions"]:
        assert re.search(rf"{d['id']} {re.escape(d['name'])}（权重 {d['weight']}）", system_prompt), d["id"]
    for b in rubric["bonus"]["items"]:
        assert f"最多 +{b['max']}" in system_prompt, b["id"]
    assert f"上限 +{rubric['bonus']['cap']}" in system_prompt
    sev = rubric["deductions"]["severity"]
    assert f"轻 −{sev['light']} / 中 −{sev['medium']} / 重 −{sev['heavy']}" in system_prompt
    assert f"最多扣 {rubric['deductions']['cap']}" in system_prompt
    assert f"同一类型最多扣 {rubric['deductions']['per_type_cap']}" in system_prompt
    assert "1 条 0 分；2 条 1 分；3~4 条 2 分；≥5 条 3 分" in system_prompt
    assert "<1500 字 0 分；1500~1999 字 1 分；2000~3500 字 2 分；>3500 字 −0.5 分" in system_prompt
    ref = rubric["deductions"]["html_to_model_severity_reference"]
    assert f"少于 {rubric['deductions']['html_to_model_min_chars']} 字的 HTML 不扣" in system_prompt
    assert f"{ref['light']} 字起轻、{ref['medium']} 字起中、{ref['heavy']} 字起重" in system_prompt
    cref = rubric["lorebook_reference"]["constant_chars_reference"]
    assert f"约 {cref['light']} 字以内算轻，超过 {cref['heavy']} 字算重" in system_prompt


def test_user_template_placeholders():
    text = (PROMPTS / "user_template.md").read_text(encoding="utf-8")
    for ph in ("[[PRECOMPUTED_STATS]]", "[[CARD_CONTENT]]", "[[BOUNDARY]]", "[[LOCATIONS]]",
               "[[SEGMENT_INDEX]]", "[[SEGMENT_TOTAL]]", "[[SEGMENT_RESULTS]]", "[[ALL_LOCATIONS]]"):
        assert ph in text, ph
