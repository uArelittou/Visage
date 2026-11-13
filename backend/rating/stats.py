"""预计算统计：清单以 rubric.json 的 precomputed_stats 为准，数字由程序数，不交给模型。"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .blocks import (
    PROMPT_FIELDS, Block, Greeting, LoreEntry, greetings, lore_entries, regex_scope,
    regex_sent_to_model, as_str,
)
from .rubric import load_rubric, tier_score

# 只把真实 HTML 元素算作 HTML；<核心规则>、<JSONPatch>、<status_current_variables> 这类语义包裹标签不算。
_HTML_ELEMENTS = (
    "a|abbr|article|aside|audio|b|blockquote|body|br|button|canvas|caption|center|code|col|details|dialog|div|dl|dt|dd|"
    "em|fieldset|figure|font|footer|form|h[1-6]|head|header|hr|html|i|iframe|img|input|label|li|link|main|meta|nav|"
    "ol|option|p|pre|progress|section|select|small|source|span|strong|style|sub|summary|sup|svg|path|circle|rect|"
    "script|table|tbody|td|textarea|tfoot|th|thead|tr|u|ul|video"
)
_REAL_HTML_TAG = re.compile(rf"<\s*/?\s*(?:{_HTML_ELEMENTS})\b[^<>]*>", re.I)
# 数字口径（开场白字数）里「其余 HTML 标签」按任意英文标签删，与试评脚本保持同一口径
_ANY_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^<>]*>")
_STYLE_SCRIPT = re.compile(r"<(style|script)\b[\s\S]*?</\1>", re.I)
_HTML_FENCE = re.compile(r"```html[\s\S]*?```")
_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_JS_UNICODE_PROP = re.compile(r"\\[pP]\{[^}]*\}")
_WS = re.compile(r"\s+")


# ------------------------------------------------------------------ JS 正则
def compile_js_regex(src: str) -> re.Pattern[str]:
    """按 /pattern/flags 或裸 pattern 解析，近似 JS 语义；失败抛 re.error。"""
    m = re.fullmatch(r"/(.*)/([a-z]*)", src or "", re.S)
    pat, flags = (m.group(1), m.group(2)) if m else (src or "", "")
    f = (re.I if "i" in flags else 0) | (re.S if "s" in flags else 0) | (re.M if "m" in flags else 0)
    pat = re.sub(r"\(\?<(?![=!])", "(?P<", pat)  # JS 命名组 -> Python
    pat = re.sub(r"\\k<([^>]+)>", r"(?P=\1)", pat)
    pat = re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda mm: "\\U%08x" % int(mm.group(1), 16), pat)
    # Python 的 re 不认 \p{..}；这里只为判断能否编译，用 \w 占位，避免把合法的 JS 正则误报为无法编译
    pat = _JS_UNICODE_PROP.sub(r"\\w", pat)
    return re.compile(pat, f)


# ------------------------------------------------------------------ 字数 / HTML
def html_chars(text: str) -> int:
    total = sum(len(m) for m in _HTML_FENCE.findall(text))
    rest = _HTML_FENCE.sub("", text)
    total += sum(len(m.group(0)) for m in _STYLE_SCRIPT.finditer(rest))
    rest = _STYLE_SCRIPT.sub("", rest)
    return total + sum(len(m) for m in _REAL_HTML_TAG.findall(rest))


def _display_strippers(card: Any) -> list[tuple[re.Pattern[str], bool]]:
    """已启用、仅格式显示的正则，按卡里的顺序。第二项为 True 表示替换成了界面（非空替换）。

    顺序要保留：常见写法是先用一条正则把 <game_text> 渲染成界面，再用一条同样的查找、替换为空的
    「删除」兜底。酒馆里前一条已经吃掉了标签，后一条匹配不到；只看替换为空的那条，就会把正文整段删掉。"""
    out = []
    for r in getattr(card, "regex_scripts", None) or []:
        if r.get("disabled") or not r.get("markdownOnly"):
            continue
        try:
            out.append((compile_js_regex(as_str(r.get("findRegex"))), bool(as_str(r.get("replaceString")))))
        except re.error:
            pass
    return out


def _keep_groups(m: re.Match[str]) -> str:
    # 渲染成界面的块：界面本身不算字，捕获组里的正文是玩家实际读到的，要算
    return "".join(g for g in m.groups() if g)


def greeting_body_chars(text: str, strippers: list[tuple[re.Pattern[str], bool]]) -> int:
    t = re.sub(r"<UpdateVariable>[\s\S]*?</UpdateVariable>", "", text, flags=re.I)
    t = re.sub(r"<initvar>[\s\S]*?</initvar>", "", t, flags=re.I)
    t = re.sub(r"\[initvar\][\s\S]*?\[/initvar\]", "", t, flags=re.I)
    for rx, rendered in strippers:
        t = rx.sub(_keep_groups if rendered else "", t)
    t = _CODE_FENCE.sub("", t)
    t = _STYLE_SCRIPT.sub("", t)
    t = _ANY_TAG.sub("", t)
    return len(_WS.sub("", t))


# ------------------------------------------------------------------ 各项统计
def _greeting_stats(gs: list[Greeting], strippers, rubric) -> list[dict[str, Any]]:
    table = rubric["opening"]["length_score"]
    out = []
    for g in gs:
        n = greeting_body_chars(g.text, strippers)
        out.append({
            "index": g.index, "location": g.location, "chars": n, "length_score": tier_score(table, n),
        })
    return out


def _lore_stats(entries: list[LoreEntry], greeting_list: list[Greeting], rubric) -> dict[str, Any]:
    mvu_pats = [re.compile(p) for p in rubric["lorebook_reference"]["mvu_expected_disabled_patterns"]]
    enabled = [e for e in entries if e.enabled]
    const = [e for e in enabled if e.constant]
    green = [e for e in enabled if not e.constant]

    owners: dict[str, list[str]] = defaultdict(list)
    display: dict[str, str] = {}
    for e in enabled:
        for k in e.keys:
            norm = k.casefold()
            display.setdefault(norm, k)
            owners[norm].append(e.location)
    collisions = [
        {"keyword": display[k], "locations": locs} for k, locs in owners.items() if len(locs) > 1
    ]

    dead, mvu_closed = [], []
    for e in entries:
        if not e.enabled:
            if any(p.search(e.name) for p in mvu_pats):
                mvu_closed.append({"location": e.location, "name": e.name})
            else:
                dead.append({"location": e.location, "name": e.name, "why": "条目关闭"})
        elif not e.constant and not e.keys:
            dead.append({"location": e.location, "name": e.name, "why": "绿灯无关键词"})

    always = "\n".join([*(e.content for e in const), *(g.text for g in greeting_list)])
    unmentioned = [
        {"location": e.location, "name": e.name, "keys": list(e.keys)}
        for e in green if e.keys and not any(k in always for k in e.keys)
    ]
    return {
        "counts": {
            "total": len(entries), "enabled": len(enabled), "constant": len(const),
            "selective": len(green), "disabled": len(entries) - len(enabled),
        },
        "constant_total": {
            "total": sum(len(e.content) for e in const),
            "per_entry": [
                {"location": e.location, "name": e.name, "chars": len(e.content)} for e in const
            ],
        },
        "collisions": collisions, "dead": dead, "unmentioned": unmentioned, "mvu_closed": mvu_closed,
    }


def _duplicate_paragraphs(blocks: list[tuple[str, str]]) -> list[dict[str, Any]]:
    seen: dict[str, list[str]] = defaultdict(list)
    for loc, text in blocks:
        for line in text.split("\n"):
            norm = _WS.sub("", line)
            if len(norm) >= 40:
                seen[norm].append(loc)
    return [
        {"text_head": k[:40], "occurrences": len(v), "locations": list(dict.fromkeys(v))}
        for k, v in seen.items() if len(v) > 1
    ]


def compute_stats(card: Any, blocks: list[Block] | None = None, rubric: dict | None = None) -> dict[str, Any]:
    from .blocks import card_blocks

    rubric = rubric or load_rubric()
    blocks = blocks if blocks is not None else card_blocks(card)
    gs = greetings(card)
    entries = lore_entries(card)
    strippers = _display_strippers(card)

    lore = _lore_stats(entries, gs, rubric)
    regexes = [r for r in (getattr(card, "regex_scripts", None) or [])]

    # 「仅格式提示词」且替换为空的正则会从提示词里删掉内容，统计 HTML 前先扣掉
    prompt_strippers = []
    for r in regexes:
        if r.get("disabled") or not r.get("promptOnly") or as_str(r.get("replaceString")):
            continue
        try:
            prompt_strippers.append(compile_js_regex(as_str(r.get("findRegex"))))
        except re.error:
            pass

    regex_compile, regex_html = [], []
    for i, r in enumerate(regexes):
        err = None
        try:
            compile_js_regex(as_str(r.get("findRegex")))
        except re.error as ex:
            err = str(ex)
        name = as_str(r.get("scriptName"))
        loc = f"正则#{i}"
        regex_compile.append({"location": loc, "name": name, "compiles": err is None, "error": err})
        regex_html.append({
            "location": loc, "name": name, "scope": regex_scope(r),
            "enabled": not r.get("disabled"),
            "html_chars": html_chars(as_str(r.get("replaceString"))),
            "sent_to_model": regex_sent_to_model(r),
        })

    prompt_blocks = [
        b for b in blocks
        if b.in_prompt and (b.kind in ("greeting", "lore", "depth_prompt")
                            or (b.kind == "field" and b.location.split(":", 1)[1] in PROMPT_FIELDS))
    ]
    html_in_prompt = []
    for b in prompt_blocks:
        text = b.text
        for rx in prompt_strippers:
            text = rx.sub("", text)
        n = html_chars(text)
        if n:
            html_in_prompt.append({"location": b.location, "html_chars": n})

    dup_source = [(b.location, b.text) for b in prompt_blocks if b.kind != "depth_prompt"]

    not_applicable = []
    if lore["counts"]["enabled"] == 0:
        not_applicable += ["lorebook_structure", "lorebook_placement"]
    if not gs:
        not_applicable.append("opening")

    return {
        "greeting_count": len(gs),
        "greeting_lengths": _greeting_stats(gs, strippers, rubric),
        "lorebook_entry_counts": lore["counts"],
        "constant_total_chars": lore["constant_total"],
        "keyword_collisions": lore["collisions"],
        "dead_entries": lore["dead"],
        "selective_keys_not_mentioned": lore["unmentioned"],
        "mvu_closed_entries": lore["mvu_closed"],
        "duplicate_paragraphs": _duplicate_paragraphs(dup_source),
        "regex_compile": regex_compile,
        "regex_html": regex_html,
        "html_in_prompt": html_in_prompt,
        "program_not_applicable": not_applicable,
    }
