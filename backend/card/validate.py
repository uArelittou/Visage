"""角色卡血统鉴定（移植自参考项目 cardLoader.js 的 isCharacterCardData / getCardRejectReason）。"""
from __future__ import annotations

import re
from typing import Any

_SPEC_RE = re.compile(r"^chara_card_v[23]$", re.IGNORECASE)
_CONTENT_FIELDS = ("description", "personality", "first_mes", "scenario", "mes_example")


def _non_empty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def is_character_card_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    # 聊天记录 / 独立世界书 / UI 主题 都不是角色卡
    if data.get("messages") or data.get("chat_metadata"):
        return False
    if "entries" in data:
        return False
    inner = data.get("data")
    if isinstance(inner, dict) and "entries" in inner and not inner.get("character_book"):
        return False
    if data.get("colors") or data.get("user_settings"):
        return False

    spec = data.get("spec")
    if isinstance(spec, str) and _SPEC_RE.match(spec.strip()):
        return isinstance(inner, dict)
    # 参考项目会在规范化阶段把「无 spec 但有 data」补成 V2，这里同样放行（要求 data 内有角色名）
    if spec is None and isinstance(inner, dict) and _non_empty_str(inner.get("name")):
        return True
    if _non_empty_str(data.get("name")):
        if data.get("system_settings") or data.get("api_keys") or data.get("public_api"):
            return False
        return any(isinstance(data.get(k), str) for k in _CONTENT_FIELDS)
    return False


def get_card_reject_reason(data: Any) -> str:
    if not isinstance(data, dict):
        return "非对象数据"
    if data.get("messages") or data.get("chat_metadata"):
        return "聊天记录导出"
    if "entries" in data:
        return "独立世界书(顶层 entries)"
    inner = data.get("data")
    if isinstance(inner, dict) and "entries" in inner and not inner.get("character_book"):
        return "独立世界书(data.entries)"
    if data.get("colors") or data.get("user_settings"):
        return "UI 主题配置"
    if _non_empty_str(data.get("name")):
        if data.get("system_settings") or data.get("api_keys") or data.get("public_api"):
            return "酒馆配置文件(config)"
        if any(k in data for k in ("apiType", "openAIKey", "jailbreak")):
            return "破限/API 配置文件"
        if any(k in data for k in ("disableSend", "injectInput", "placeBeforeInput")):
            return "快速回复集(QR)"
        t = data.get("type")
        if t and not re.match(r"^chara_card", str(t), re.IGNORECASE):
            return "自定义类型文件"
        return "缺少角色内容字段(description/personality/first_mes 等)"
    if isinstance(data.get("spec"), str):
        return "未知 spec 版本或缺少 data"
    if data.get("type"):
        return "自定义类型文件"
    return "无角色名且无 spec 标记"
