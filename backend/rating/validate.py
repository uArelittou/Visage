"""校验模型输出：解析 JSON、按 output_schema.json 做结构校验、核对分数范围和引用原句。

venv 里没有 jsonschema，这里只实现 output_schema.json 用到的那部分关键字：
$ref(内部)、type、const、enum、properties、required、additionalProperties、items、
minItems、uniqueItems、minLength、maxLength、minimum、maximum、oneOf、allOf。
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .rubric import load_schema

MAX_REPORTED_ERRORS = 30


class OutputError(Exception):
    """模型输出无法通过校验；errors 是逐条的具体问题，可原样反馈给模型。"""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors[:5]))


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    output: dict[str, Any] | None = None  # 去掉了无效引用的副本；有 errors 时不可用

    @property
    def ok(self) -> bool:
        return not self.errors


# ------------------------------------------------------------------ JSON 解析
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n([\s\S]*?)\n?```\s*$")


def parse_json_text(text: str) -> Any:
    s = (text or "").strip().lstrip("\ufeff")
    if not s:
        raise OutputError(["输出为空，需要一个 JSON 对象"])
    m = _FENCE.match(s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except ValueError as first:
        # 模型偶尔在 JSON 前后加一句说明；取最外层花括号再试一次
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                pass
        raise OutputError([f"输出不是合法 JSON: {first}"]) from None


# ------------------------------------------------------------------ 迷你 JSON Schema
def _json_eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _type_ok(inst: Any, t: str) -> bool:
    if t == "object":
        return isinstance(inst, dict)
    if t == "array":
        return isinstance(inst, list)
    if t == "string":
        return isinstance(inst, str)
    if t == "boolean":
        return isinstance(inst, bool)
    if t == "null":
        return inst is None
    if t == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool)
    if t == "integer":
        return (isinstance(inst, int) and not isinstance(inst, bool)) or (
            isinstance(inst, float) and inst.is_integer()
        )
    return True


def _resolve(root: dict[str, Any], ref: str) -> dict[str, Any]:
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _short(v: Any) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v)
    return s if len(s) <= 40 else s[:37] + "..."


def _check(inst: Any, schema: Any, root: dict[str, Any], path: str, out: list[str]) -> None:
    if schema is True or schema is None:
        return
    if schema is False:
        out.append(f"{path}: 不允许出现")
        return
    if "$ref" in schema:
        _check(inst, _resolve(root, schema["$ref"]), root, path, out)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(inst, t) for t in types):
            out.append(f"{path}: 类型应为 {'/'.join(types)}，实际是 {_short(inst)}")
            return
    if "const" in schema and not _json_eq(inst, schema["const"]):
        out.append(f"{path}: 必须是 {_short(schema['const'])}，实际是 {_short(inst)}")
    if "enum" in schema and not any(_json_eq(inst, v) for v in schema["enum"]):
        out.append(f"{path}: 取值必须是 {schema['enum']} 之一，实际是 {_short(inst)}")

    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            out.append(f"{path}: 不能小于 {schema['minimum']}，实际是 {inst}")
        if "maximum" in schema and inst > schema["maximum"]:
            out.append(f"{path}: 不能大于 {schema['maximum']}，实际是 {inst}")
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            out.append(f"{path}: 至少 {schema['minLength']} 个字符")
        if "maxLength" in schema and len(inst) > schema["maxLength"]:
            out.append(f"{path}: 最多 {schema['maxLength']} 个字符，实际 {len(inst)} 个，请缩短")
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            out.append(f"{path}: 至少需要 {schema['minItems']} 项，实际 {len(inst)} 项")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in inst}) != len(inst):
            out.append(f"{path}: 不允许重复项")
        if "items" in schema:
            for i, item in enumerate(inst):
                _check(item, schema["items"], root, f"{path}[{i}]", out)
    if isinstance(inst, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in inst:
                out.append(f"{path}: 缺少必填字段 {name!r}")
        add = schema.get("additionalProperties", True)
        for key, val in inst.items():
            sub = f"{path}.{key}" if path else key
            if key in props:
                _check(val, props[key], root, sub, out)
            elif add is False:
                out.append(f"{sub}: 不允许的多余字段")
            elif isinstance(add, dict):
                _check(val, add, root, sub, out)
    for sub_schema in schema.get("allOf", []):
        _check(inst, sub_schema, root, path, out)
    if "oneOf" in schema:
        results = []
        for branch in schema["oneOf"]:
            errs: list[str] = []
            _check(inst, branch, root, path, errs)
            results.append(errs)
        passed = sum(1 for e in results if not e)
        if passed == 0:
            # 没有分支通过时只报错误最少的那个分支，其余分支的错误与实际意图无关
            out.extend(min(results, key=len))
        elif passed > 1:
            out.append(f"{path}: 同时符合多种结构，无法确定")


def check_schema(instance: Any, schema: dict[str, Any] | None = None) -> list[str]:
    schema = schema or load_schema()
    errs: list[str] = []
    _check(instance, schema, schema, "$", errs)
    return [e.replace("$.", "", 1) if e.startswith("$.") else e for e in errs]


# ------------------------------------------------------------------ 引用核对
def normalize(s: str) -> str:
    """去掉空白、标点、符号、控制字符，全角转半角，忽略大小写。模型常在这些地方和原文不一致。"""
    s = unicodedata.normalize("NFKC", s).casefold()
    return "".join(ch for ch in s if unicodedata.category(ch)[0] not in "ZPSC")


def label_of(location: str) -> str:
    """模型有时把 `| 附加信息` 一起抄进 location，只取标签。"""
    return location.split("|", 1)[0].strip()


class QuoteIndex:
    def __init__(self, texts: dict[str, str]):
        self._norm = {loc: normalize(t) for loc, t in texts.items()}

    def __contains__(self, location: str) -> bool:
        return label_of(location) in self._norm

    def problem(self, quote: dict[str, Any]) -> str | None:
        loc = label_of(quote["location"])
        if loc not in self._norm:
            return f"位置标签 {loc!r} 不在区块清单里"
        nq = normalize(quote["quote"])
        if len(nq) < 2:
            return f"原句 {_short(quote['quote'])} 去掉标点空白后不足 2 个字"
        if nq not in self._norm[loc]:
            return f"原句 {_short(quote['quote'])} 在 {loc} 里找不到（必须逐字连续摘录）"
        return None


def _prune(
    quotes: list[dict[str, Any]], idx: QuoteIndex, where: str
) -> tuple[list[dict[str, Any]], list[str]]:
    good, bad = [], []
    for q in quotes:
        p = idx.problem(q)
        if p:
            bad.append(f"{where}: {p}")
        else:
            good.append({"quote": q["quote"], "location": label_of(q["location"])})
    return good, bad


def _need_evidence(
    quotes: list[dict[str, Any]], idx: QuoteIndex, where: str, errors: list[str], warnings: list[str]
) -> list[dict[str, Any]]:
    good, bad = _prune(quotes, idx, where)
    if not good:
        errors.append(f"{where}: 没有一条有效引用，" + ("；".join(bad) if bad else "evidence 为空"))
    else:
        warnings.extend(bad)
    return good


# ------------------------------------------------------------------ 语义校验
def _check_greetings(
    greetings: list[dict[str, Any]], expected: set[int], idx: QuoteIndex, where: str,
    errors: list[str], warnings: list[str], require_all: bool,
) -> list[dict[str, Any]]:
    seen: set[int] = set()
    out = []
    for i, g in enumerate(greetings):
        tag = f"{where}[{i}](index={g['index']})"
        if g["index"] in seen:
            errors.append(f"{tag}: index 重复")
            continue
        seen.add(g["index"])
        if g["index"] not in expected:
            errors.append(f"{tag}: 没有这条开场白，有效 index 是 {sorted(expected)}")
            continue
        item = copy.deepcopy(g)
        item["guidance_evidence"] = _need_evidence(
            g["guidance_evidence"], idx, f"{tag}.guidance_evidence", errors, warnings)
        item["freedom_evidence"] = _need_evidence(
            g["freedom_evidence"], idx, f"{tag}.freedom_evidence", errors, warnings)
        out.append(item)
    if require_all and expected - seen:
        errors.append(f"{where}: 缺少开场白 index {sorted(expected - seen)} 的判定，必须覆盖统计里的每一条")
    return out


def validate_final(
    obj: Any, *, stats: dict[str, Any], quotes: QuoteIndex
) -> ValidationResult:
    res = ValidationResult()
    if not isinstance(obj, dict) or obj.get("mode") != "final":
        res.errors.append('应输出 mode="final" 的 JSON 对象')
        return res
    res.errors.extend(check_schema(obj))
    if res.errors:
        return res
    out = copy.deepcopy(obj)
    errors, warnings = res.errors, res.warnings
    dims = out["dimensions"]

    declared = set(out["not_applicable"])
    actual = {k for k, v in dims.items() if not v["applicable"]}
    if declared != actual:
        errors.append(
            f"not_applicable {sorted(declared)} 与各维度 applicable=false 的 {sorted(actual)} 不一致"
        )

    program_na = set(stats.get("program_not_applicable", []))
    for dim_id, dim in dims.items():
        if dim_id in program_na:
            continue  # 程序已判定不适用，模型怎么写都不采用，也就不核对引用
        where = f"dimensions.{dim_id}"
        if not dim["applicable"]:
            if dim_id in ("lorebook_structure", "lorebook_placement", "opening"):
                errors.append(f"{where}: 预计算统计显示该项适用，不能标为不适用")
            continue
        if dim_id == "opening":
            expected = {g["index"] for g in stats["greeting_lengths"]}
            dim["greetings"] = _check_greetings(
                dim["greetings"], expected, quotes, f"{where}.greetings", errors, warnings, True)
        else:
            dim["evidence"] = _need_evidence(dim["evidence"], quotes, f"{where}.evidence", errors, warnings)

    for bid, b in out["bonus"].items():
        where = f"bonus.{bid}"
        if b["score"] > 0:
            b["evidence"] = _need_evidence(b["evidence"], quotes, f"{where}.evidence", errors, warnings)
        else:
            b["evidence"], bad = _prune(b["evidence"], quotes, f"{where}.evidence")
            warnings.extend(bad)

    for i, d in enumerate(out["deductions"]):
        for j, q in enumerate(d["quotes"]):
            p = quotes.problem(q)
            if p:
                errors.append(f"deductions[{i}].quotes[{j}]: {p}")
            else:
                q["location"] = label_of(q["location"])

    out["injection_notes"], bad = _prune(out["injection_notes"], quotes, "injection_notes")
    warnings.extend(bad)

    # 只警告不打回：角色名、卡名里可能本来就带这些字，重打要花钱
    found = sorted(set(_PRONOUN.findall(out["review"])))
    if found:
        warnings.append(f"review: 出现人称代词 {''.join(found)}")

    res.output = out if not errors else None
    return res


_PRONOUN = re.compile(r"[你您我她它]|(?<!其)他")


def validate_segment(
    obj: Any, *, stats: dict[str, Any], quotes: QuoteIndex, index: int, total: int,
    segment_locations: list[str],
) -> ValidationResult:
    res = ValidationResult()
    if not isinstance(obj, dict) or obj.get("mode") != "segment":
        res.errors.append('应输出 mode="segment" 的 JSON 对象')
        return res
    res.errors.extend(check_schema(obj))
    if res.errors:
        return res
    out = copy.deepcopy(obj)
    errors, warnings = res.errors, res.warnings
    if out["segment_index"] != index or out["segment_total"] != total:
        errors.append(f"segment_index/segment_total 应为 {index}/{total}")

    if set(out["locations_read"]) != set(segment_locations):
        warnings.append("locations_read 与本段实际区块不一致，已按实际区块覆盖")
    out["locations_read"] = list(segment_locations)

    notes = []
    for i, n in enumerate(out["notes"]):
        good, bad = _prune(n["evidence"], quotes, f"notes[{i}].evidence")
        if good:
            n["evidence"] = good
            notes.append(n)
            warnings.extend(bad)
        else:
            warnings.append(f"notes[{i}] 没有有效引用，已丢弃")
    out["notes"] = notes

    facts = []
    for i, f in enumerate(out["facts"]):
        p = quotes.problem(f["evidence"])
        if p:
            warnings.append(f"facts[{i}] 引用无效，已丢弃: {p}")
        else:
            f["evidence"]["location"] = label_of(f["evidence"]["location"])
            facts.append(f)
    out["facts"] = facts

    expected = {g["index"] for g in stats["greeting_lengths"]}
    out["greetings"] = _check_greetings(
        out["greetings"], expected, quotes, "greetings", errors, warnings, False)

    cands = []
    for i, d in enumerate(out["deduction_candidates"]):
        bad = [quotes.problem(q) for q in d["quotes"]]
        if any(bad):
            warnings.append(f"deduction_candidates[{i}] 引用无效，已丢弃: {next(b for b in bad if b)}")
        else:
            for q in d["quotes"]:
                q["location"] = label_of(q["location"])
            cands.append(d)
    out["deduction_candidates"] = cands

    out["injection_notes"], bad = _prune(out["injection_notes"], quotes, "injection_notes")
    warnings.extend(bad)

    res.output = out if not errors else None
    return res
