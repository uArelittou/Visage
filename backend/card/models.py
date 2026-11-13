"""角色卡数据模型：V1/V2/V3 统一为 Card，未知字段保留在 raw / extensions 中。"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

SPEC_V1 = "chara_card_v1"
SPEC_V2 = "chara_card_v2"
SPEC_V3 = "chara_card_v3"

_WRAPPED_SPEC_RE = re.compile(r"^chara_card_v[23]$", re.IGNORECASE)

_STR_FIELDS = (
    "name", "description", "personality", "scenario", "first_mes", "mes_example",
    "creator", "creator_notes", "character_version", "system_prompt",
    "post_history_instructions",
)
_LIST_FIELDS = ("tags", "alternate_greetings")

# 酒馆助手旧版脚本容器键（与参考项目 cardPlugins.js LEGACY_SCRIPT_KEYS 一致）
_LEGACY_SCRIPT_KEYS = (
    "TavernHelper_scripts", "tavern_helper_scripts", "tavernHelper_scripts", "tavernHelper",
)


class CardParseError(Exception):
    """文件无法解析为角色卡。"""


class CardWriteError(Exception):
    """角色卡无法安全写回（目标冲突、写后校验失败等）。"""


def _s(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_s(v) for v in value if v is not None]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []


def _split_layers(raw: dict) -> tuple[str, dict, dict | None]:
    """返回 (spec, 数据层, 外层)。V1 平铺卡的外层为 None，数据层即 raw 本身。"""
    spec_raw = raw.get("spec")
    data = raw.get("data")
    if isinstance(spec_raw, str) and _WRAPPED_SPEC_RE.match(spec_raw.strip()):
        if not isinstance(data, dict):
            raise CardParseError(f"spec={spec_raw} 但缺少 data 对象")
        return spec_raw.strip().lower(), data, raw
    if spec_raw is None and isinstance(data, dict):
        # 参考项目 normalizeCardData：无 spec 但有 data 视为 V2
        return SPEC_V2, data, raw
    if isinstance(data, dict) and isinstance(spec_raw, str) and spec_raw.strip().lower() != SPEC_V1:
        raise CardParseError(f"未知 spec 版本: {spec_raw}")
    return SPEC_V1, raw, None


@dataclass
class Card:
    name: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    alternate_greetings: list[str] = field(default_factory=list)
    creator: str = ""
    creator_notes: str = ""
    tags: list[str] = field(default_factory=list)
    character_version: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    character_book: dict | None = None
    extensions: dict = field(default_factory=dict)
    spec: str = SPEC_V2
    # 原始解析结果；用于保留未知字段。比较时忽略：V2 卡写回后会以 ccv3(V3) 形态读回，布局必然不同。
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    # ---------------------------------------------------------------- 构造
    @classmethod
    def from_dict(cls, raw: dict) -> "Card":
        """由 V1/V2/V3 JSON 构造。extensions / character_book 与 raw 共享引用。"""
        if not isinstance(raw, dict):
            raise CardParseError("角色卡数据不是 JSON 对象")
        spec, data, root = _split_layers(raw)

        def pick(key: str) -> Any:
            if key in data:
                return data[key]
            if root is not None and key in root:  # V2 混合卡：字段仅在外层平铺
                return root[key]
            return None

        book = pick("character_book")
        if isinstance(book, list):  # 老 V1 嵌入形态：条目数组
            book = {"entries": book}
        elif not isinstance(book, dict):
            book = None
        ext = pick("extensions")
        return cls(
            **{k: _s(pick(k)) for k in _STR_FIELDS},
            alternate_greetings=_str_list(pick("alternate_greetings")),
            tags=_str_list(pick("tags")),
            character_book=book,
            extensions=ext if isinstance(ext, dict) else {},
            spec=spec,
            raw=raw,
        )

    # ---------------------------------------------------------------- 脚本
    @property
    def regex_scripts(self) -> list[dict]:
        """extensions.regex_scripts（兼容 regexScripts）。"""
        for key in ("regex_scripts", "regexScripts"):
            v = self.extensions.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return []

    @property
    def scripts(self) -> list[dict]:
        """酒馆助手脚本。旧版 {type, value:{...}} 包装会被拆开返回 value（同一对象，可原地编辑）。"""
        out: list[dict] = []
        for item in _find_script_list(self.extensions):
            _flatten_script(item, out)
        return out

    # ---------------------------------------------------------------- 序列化
    def _field_values(self) -> dict[str, Any]:
        vals: dict[str, Any] = {k: getattr(self, k) for k in _STR_FIELDS}
        vals["alternate_greetings"] = list(self.alternate_greetings)
        vals["tags"] = list(self.tags)
        vals["extensions"] = self.extensions if isinstance(self.extensions, dict) else {}
        vals["character_book"] = self.character_book
        return vals

    def _build(self, spec: str, version: str) -> dict:
        raw = copy.deepcopy(self.raw) if isinstance(self.raw, dict) else {}
        try:
            _, data, root = _split_layers(raw)
        except CardParseError:
            data, root = raw, None
        if root is None:
            # 平铺卡：除 spec 标记外的所有键（含未知键）都进入 data 层，与参考项目一致
            data = {k: v for k, v in raw.items() if k not in ("spec", "spec_version", "data")}
            root = {}
        else:
            root = {k: v for k, v in root.items() if k not in ("spec", "spec_version", "data")}

        vals = copy.deepcopy(self._field_values())
        for key, value in vals.items():
            if key == "character_book" and value is None:
                data.pop(key, None)
                root.pop(key, None)
                continue
            data[key] = value
            if key in root:  # 外层平铺的同名字段保持同步，避免读到旧值
                root[key] = copy.deepcopy(value)
        if spec == SPEC_V3:
            if not isinstance(data.get("group_only_greetings"), list):
                data["group_only_greetings"] = []
        return {"spec": spec, "spec_version": version, **root, "data": data}

    def to_v2_dict(self) -> dict:
        return self._build(SPEC_V2, "2.0")

    def to_v3_dict(self) -> dict:
        return self._build(SPEC_V3, "3.0")


# -------------------------------------------------------------------- 脚本容器解析
def _is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def _looks_like_script_array(arr: list) -> bool:
    return bool(arr) and all(
        _is_obj(it) and any(k in it for k in ("value", "content", "type", "name")) for it in arr
    )


def _find_script_list(ext: dict) -> list:
    helper = ext.get("tavern_helper")
    if isinstance(helper, list):
        for pair in helper:  # 键值对数组形态 [["scripts", [...]], ["variables", {...}]]
            if isinstance(pair, list) and len(pair) == 2 and pair[0] == "scripts":
                return pair[1] if isinstance(pair[1], list) else []
        if _looks_like_script_array(helper):
            return helper
    elif isinstance(helper, dict):
        for key in ("scripts", "script"):
            if isinstance(helper.get(key), list):
                return helper[key]
    for key in _LEGACY_SCRIPT_KEYS:
        if isinstance(ext.get(key), list):
            return ext[key]
    return []


def _flatten_script(item: Any, out: list[dict]) -> None:
    if not _is_obj(item):
        return
    if item.get("type") == "folder" and isinstance(item.get("scripts"), list):
        for child in item["scripts"]:
            _flatten_script(child, out)
        return
    host = item.get("value")
    out.append(host if _is_obj(host) else item)
