"""按 prompts/user_template.md 拼发给评分模型的消息：整卡 / 分段 / 合并。"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import Any

from .blocks import Block
from .rubric import load_system_prompt, load_user_template

_PLACEHOLDER = re.compile(r"\[\[([A-Z_]+)\]\]")
_TEMPLATE_HEADS = {"A": "模板 A：整卡模式", "B": "模板 B：分段模式", "C": "模板 C：合并模式"}
# 为序号位数、边界码等小波动留的余量
_SLACK = 400
_MIN_SEGMENT_ROOM = 2000


class PromptError(Exception):
    pass


def _template(kind: str) -> str:
    text = load_user_template()
    m = re.search(rf"## {re.escape(_TEMPLATE_HEADS[kind])}[^\n]*\n\s*```\n([\s\S]*?)```", text)
    if not m:
        raise PromptError(f"user_template.md 里找不到 {_TEMPLATE_HEADS[kind]}")
    return m.group(1)


def fill(template: str, values: dict[str, str]) -> str:
    """一次性替换全部占位符，替换进去的内容（卡文本里的 [[…]] 等）不会再被处理。"""

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in values:
            raise PromptError(f"模板占位符 [[{name}]] 没有提供取值")
        return values[name]

    return _PLACEHOLDER.sub(sub, template)


def new_boundary(*texts: str) -> str:
    while True:
        code = secrets.token_hex(8)
        if not any(code in t for t in texts):
            return code


def stats_json(stats: dict[str, Any]) -> str:
    return json.dumps(stats, ensure_ascii=False, indent=2)


@dataclass
class Message:
    """一次调用的两条消息，以及这次发了哪些区块标签（用于核对引用范围）。"""

    system: str
    user: str
    locations: list[str]

    def chat(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": self.user}]

    @property
    def size(self) -> int:
        return len(self.system) + len(self.user)


def _content(blocks: list[Block]) -> str:
    return "\n\n".join(b.render() for b in blocks)


def build_full(blocks: list[Block], stats: dict[str, Any]) -> Message:
    content = _content(blocks)
    locations = [b.location for b in blocks]
    loc_text = "\n".join(locations)
    st = stats_json(stats)
    boundary = new_boundary(content)
    user = fill(_template("A"), {
        "PRECOMPUTED_STATS": st, "LOCATIONS": loc_text,
        "BOUNDARY": boundary, "CARD_CONTENT": content,
    })
    return Message(load_system_prompt(), user, locations)


def build_segment(
    blocks: list[Block], stats: dict[str, Any], all_locations: list[str], index: int, total: int
) -> Message:
    content = _content(blocks)
    locations = [b.location for b in blocks]
    boundary = new_boundary(content)
    user = fill(_template("B"), {
        "SEGMENT_INDEX": str(index), "SEGMENT_TOTAL": str(total),
        "PRECOMPUTED_STATS": stats_json(stats), "ALL_LOCATIONS": "\n".join(all_locations),
        "LOCATIONS": "\n".join(dict.fromkeys(locations)),
        "BOUNDARY": boundary, "CARD_CONTENT": content,
    })
    return Message(load_system_prompt(), user, list(dict.fromkeys(locations)))


def build_merge(
    stats: dict[str, Any], all_locations: list[str], segment_results: list[dict[str, Any]]
) -> Message:
    results = json.dumps(segment_results, ensure_ascii=False, indent=2)
    boundary = new_boundary(results)
    user = fill(_template("C"), {
        "SEGMENT_TOTAL": str(len(segment_results)), "PRECOMPUTED_STATS": stats_json(stats),
        "ALL_LOCATIONS": "\n".join(all_locations), "BOUNDARY": boundary, "SEGMENT_RESULTS": results,
    })
    return Message(load_system_prompt(), user, list(all_locations))


# ------------------------------------------------------------------ 分段
def _split_text(text: str, limit: int) -> list[str]:
    """尽量在段落边界切；单个段落超长时按行，再超长才硬切。"""
    parts: list[str] = []
    cur = ""
    for line in text.split("\n"):
        piece = line + "\n"
        while len(piece) > limit:  # 单行超长
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(piece[:limit])
            piece = piece[limit:]
        if len(cur) + len(piece) > limit and cur:
            parts.append(cur)
            cur = ""
        cur += piece
    if cur:
        parts.append(cur)
    return [p.rstrip("\n") if i == len(parts) - 1 else p for i, p in enumerate(parts)]


def _split_block(b: Block, limit: int) -> list[Block]:
    # 标题行也占长度，给它留出余量
    room = max(limit - len(b.location) - len(b.info) - 40, 200)
    if len(b.render()) <= limit:
        return [b]
    pieces = _split_text(b.text, room)
    out = []
    for k, piece in enumerate(pieces):
        info = b.info if k == 0 else (b.info + " | " if b.info else "") + f"续{k}"
        out.append(Block(b.location, info, piece, b.kind, b.in_prompt))
    return out


def plan_segments(
    blocks: list[Block], stats: dict[str, Any], all_locations: list[str], budget: int
) -> list[list[Block]]:
    """按区块顺序贪心装段，使每段完整消息不超过 budget。"""
    probe = build_segment([], stats, all_locations, 99, 99)
    room = budget - probe.size - _SLACK
    if room < _MIN_SEGMENT_ROOM:
        raise PromptError(
            f"上下文字符预算 {budget} 太小：系统提示词和统计就占了 {probe.size} 字，装不下卡内容"
        )
    segments: list[list[Block]] = []
    cur: list[Block] = []
    used = 0
    for block in blocks:
        for piece in _split_block(block, room):
            size = len(piece.render()) + 2
            if cur and used + size > room:
                segments.append(cur)
                cur, used = [], 0
            cur.append(piece)
            used += size
    if cur:
        segments.append(cur)
    return segments
