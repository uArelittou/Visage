"""把 Card 拆成带位置标签的区块。统计、拼消息、核对引用共用同一份拆分，标签才不会对不上。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

POS_NAME = {
    0: "角色定义前", 1: "角色定义后", 2: "作者注释前", 3: "作者注释后",
    4: "@depth", 5: "示例消息前", 6: "示例消息后", 7: "outlet",
}
V3_POS_NAME = {"before_char": "角色定义前", "after_char": "角色定义后"}
ROLE_NAME = {0: "system", 1: "user", 2: "assistant"}
PLACEMENT_NAME = {1: "用户输入", 2: "AI输出", 3: "快捷命令", 5: "世界书", 6: "推理"}
TEXT_FIELDS = (
    "name", "description", "personality", "scenario", "mes_example",
    "system_prompt", "post_history_instructions",
)
# 这些字段会进入发给模型的提示词；name 只是标识，不参与重复/HTML 统计
PROMPT_FIELDS = TEXT_FIELDS[1:]


@dataclass(frozen=True)
class Greeting:
    index: int
    text: str
    source: str

    @property
    def location(self) -> str:
        return f"开场白#{self.index}"


@dataclass(frozen=True)
class LoreEntry:
    location: str
    name: str
    enabled: bool
    constant: bool
    keys: tuple[str, ...]
    secondary_keys: tuple[str, ...]
    position: str
    depth: Any
    role: str
    order: Any
    content: str

    @property
    def light(self) -> str:
        return "关闭" if not self.enabled else ("蓝灯" if self.constant else "绿灯")


@dataclass(frozen=True)
class Block:
    location: str
    info: str
    text: str
    kind: str  # field / creator_notes / greeting / lore / regex / script / depth_prompt
    in_prompt: bool = True  # 是否会作为文本发给扮演模型（关闭的条目、作者笔记、正则/脚本为否）

    def render(self) -> str:
        head = f"=== {self.location}{' | ' + self.info if self.info else ''} ==="
        return f"{head}\n{self.text}"


def as_str(v: Any) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _str_tuple(v: Any) -> tuple[str, ...]:
    if isinstance(v, str):
        v = [t for t in v.split(",")]
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(s.strip() for s in (as_str(x) for x in v if x is not None) if s.strip())


def _order_key(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def greetings(card: Any) -> list[Greeting]:
    """去掉首尾空白后为空的不计；index 只在非空条目里连续编号。"""
    out: list[Greeting] = []
    first = as_str(getattr(card, "first_mes", ""))
    if first.strip():
        out.append(Greeting(len(out), first, "first_mes"))
    for i, g in enumerate(getattr(card, "alternate_greetings", None) or []):
        g = as_str(g)
        if g.strip():
            out.append(Greeting(len(out), g, f"alternate_greetings[{i}]"))
    return out


def lore_entries(card: Any) -> list[LoreEntry]:
    book = getattr(card, "character_book", None)
    raw = book.get("entries") if isinstance(book, dict) else None
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return []
    entries: list[LoreEntry] = []
    used: set[str] = set()
    for i, e in enumerate(raw):
        if not isinstance(e, dict):
            continue
        ext = e.get("extensions") if isinstance(e.get("extensions"), dict) else {}
        uid = as_str(e.get("id", i))
        loc = f"世界书#{uid}"
        if loc in used:  # 卡里 id 重复时仍要保证标签唯一，否则引用无法核对
            loc = f"世界书#{uid}_{i}"
        used.add(loc)
        pos_raw = ext.get("position")
        if isinstance(pos_raw, int) and not isinstance(pos_raw, bool):
            pos = POS_NAME.get(pos_raw, str(pos_raw))
        else:
            pos = V3_POS_NAME.get(as_str(e.get("position")), as_str(e.get("position")) or "未知")
        role_raw = ext.get("role")
        entries.append(LoreEntry(
            location=loc,
            name=as_str(e.get("comment") or e.get("name")),
            enabled=bool(e.get("enabled", True)) and not e.get("disable", False),
            constant=bool(e.get("constant")),
            keys=_str_tuple(e.get("keys")),
            secondary_keys=_str_tuple(e.get("secondary_keys")),
            position=pos,
            depth=ext.get("depth"),
            role=ROLE_NAME.get(role_raw, as_str(role_raw)) if role_raw is not None else "",
            order=e.get("insertion_order"),
            content=as_str(e.get("content")),
        ))
    entries.sort(key=lambda x: _order_key(x.order))
    return entries


def regex_scope(r: dict) -> str:
    md, po = bool(r.get("markdownOnly")), bool(r.get("promptOnly"))
    if md and po:
        return "仅显示+仅发送"
    return "仅显示" if md else "仅发送" if po else "改写原文"


def regex_sent_to_model(r: dict) -> bool:
    """酒馆里：只勾「仅格式显示」不会进提示词；勾了「仅格式提示词」或两者都没勾（改写聊天原文）都会。"""
    return not r.get("disabled") and (bool(r.get("promptOnly")) or not r.get("markdownOnly"))


def card_blocks(card: Any) -> list[Block]:
    blocks: list[Block] = []
    for f in TEXT_FIELDS:
        v = as_str(getattr(card, f, ""))
        if v.strip():
            blocks.append(Block(f"字段:{f}", "", v, "field"))
    notes = as_str(getattr(card, "creator_notes", ""))
    if notes.strip():
        blocks.append(Block("字段:creator_notes", "不评分", notes, "creator_notes", in_prompt=False))
    for g in greetings(card):
        blocks.append(Block(g.location, g.source, g.text, "greeting"))
    for e in lore_entries(card):
        info = (
            f"{e.name} | {e.light} | position={e.position} | depth={e.depth} | role={e.role}"
            f" | order={e.order} | keys={','.join(e.keys)}"
        )
        if e.secondary_keys:
            info += f" | 次要keys={','.join(e.secondary_keys)}"
        blocks.append(Block(e.location, info, e.content, "lore", in_prompt=e.enabled))
    for i, r in enumerate(getattr(card, "regex_scripts", None) or []):
        placement = r.get("placement") if isinstance(r.get("placement"), list) else []
        where = ",".join(PLACEMENT_NAME.get(p, str(p)) for p in placement)
        info = (
            f"{as_str(r.get('scriptName'))} | {'关闭' if r.get('disabled') else '启用'} | {regex_scope(r)}"
            f" | 作用于={where} | depth={r.get('minDepth')}~{r.get('maxDepth')}"
            f" | find={as_str(r.get('findRegex'))}"
        )
        blocks.append(Block(f"正则#{i}", info, as_str(r.get("replaceString")), "regex", in_prompt=False))
    for i, s in enumerate(getattr(card, "scripts", None) or []):
        enabled = s.get("enabled", True)
        info = f"{as_str(s.get('name'))} | {'启用' if enabled else '关闭'}"
        blocks.append(Block(f"脚本#{i}", info, as_str(s.get("content")), "script", in_prompt=False))
    ext = getattr(card, "extensions", None) or {}
    dp = ext.get("depth_prompt") if isinstance(ext, dict) else None
    if isinstance(dp, dict) and as_str(dp.get("prompt")).strip():
        blocks.append(Block(
            "扩展:depth_prompt", f"depth={dp.get('depth')} | role={as_str(dp.get('role'))}",
            as_str(dp.get("prompt")), "depth_prompt",
        ))
    return blocks
