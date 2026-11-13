"""rubric.json 与提示词文件的读取；所有评分数字以 rubric.json 为准。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

RATING_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = RATING_DIR / "prompts"


@lru_cache(maxsize=1)
def load_rubric() -> dict[str, Any]:
    return json.loads((RATING_DIR / "rubric.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    return json.loads((PROMPTS_DIR / "output_schema.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    return (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_user_template() -> str:
    return (PROMPTS_DIR / "user_template.md").read_text(encoding="utf-8")


def tier_score(table: list[dict[str, Any]], n: int) -> float:
    """在 {min,max,score} 区间表里查 n 对应的分；max 为 None 表示无上限。"""
    for row in table:
        if n >= row["min"] and (row["max"] is None or n <= row["max"]):
            return row["score"]
    raise ValueError(f"{n} 不在区间表内")


def dimension_ids(rubric: dict[str, Any] | None = None) -> list[str]:
    return [d["id"] for d in (rubric or load_rubric())["dimensions"]]
