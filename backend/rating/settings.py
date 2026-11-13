"""评分 API 配置。存在用户数据目录（不在项目目录，也不在用户的卡文件夹里），环境变量优先。

文件：<用户数据目录>/config.json，评分配置放在顶层键 "rating" 下，来源列表在 "library" 下，其他键原样保留。
用户数据目录：环境变量 QIANMIANLU_HOME > Windows 的 %LOCALAPPDATA%\\qianmianlu > $XDG_CONFIG_HOME/qianmianlu > ~/.config/qianmianlu。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from backend.card.fsio import atomic_write_bytes

APP_DIR_NAME = "qianmianlu"
CONFIG_FILE = "config.json"
SECTION = "rating"
ENV_PREFIX = "QIANMIANLU_RATING_"

DEFAULT_TIMEOUT = 300.0
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_RETRIES = 2
# 整条请求（系统提示词 + 统计 + 卡内容）允许的字符数；超过就走分段模式。
# 取得很大：主流模型上下文已够整卡一次发完，分段只作接口报超长时的兜底。
DEFAULT_CONTEXT_CHAR_BUDGET = 600_000


class SettingsError(ValueError):
    """配置值非法。消息里只写字段名，不回显取值（可能是密钥）。"""


@dataclass(frozen=True)
class RatingSettings:
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout: float = DEFAULT_TIMEOUT
    temperature: float | None = DEFAULT_TEMPERATURE
    max_tokens: int | None = None
    max_retries: int = DEFAULT_MAX_RETRIES
    context_char_budget: int = DEFAULT_CONTEXT_CHAR_BUDGET

    def missing(self) -> list[str]:
        return [n for n in ("base_url", "api_key", "model") if not getattr(self, n)]

    @property
    def configured(self) -> bool:
        return not self.missing()

    def masked(self) -> dict[str, Any]:
        """给界面显示用：密钥只留首尾几位。"""
        return {
            "base_url": self.base_url,
            "api_key": mask_secret(self.api_key),
            "api_key_set": bool(self.api_key),
            "model": self.model,
            "timeout": self.timeout,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_retries": self.max_retries,
            "context_char_budget": self.context_char_budget,
        }


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) < 16:
        return "*" * 8
    return f"{secret[:3]}***{secret[-4:]}"


def user_data_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("QIANMIANLU_HOME"):
        return Path(env["QIANMIANLU_HOME"])
    if sys.platform == "win32" and env.get("LOCALAPPDATA"):
        return Path(env["LOCALAPPDATA"]) / APP_DIR_NAME
    base = env.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / APP_DIR_NAME


def settings_path(env: Mapping[str, str] | None = None) -> Path:
    return user_data_dir(env) / CONFIG_FILE


def _read_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise SettingsError(f"配置文件 {path} 无法读取: {type(e).__name__}") from None
    return data if isinstance(data, dict) else {}


_CASTS = {
    "base_url": str, "api_key": str, "model": str,
    "timeout": float, "temperature": float, "max_tokens": int,
    "max_retries": int, "context_char_budget": int,
}
_NULLABLE = {"temperature", "max_tokens"}


def _coerce(name: str, value: Any) -> Any:
    if value is None or value == "":
        if name in _NULLABLE:
            return None
        if _CASTS[name] is str:
            return ""
        raise SettingsError(f"配置项 {name} 不能为空")
    try:
        out = _CASTS[name](value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        raise SettingsError(f"配置项 {name} 的类型不对") from None
    if name == "base_url":
        out = out.strip()
    if name in ("timeout", "context_char_budget") and out <= 0:
        raise SettingsError(f"配置项 {name} 必须大于 0")
    if name == "max_retries" and out < 0:
        raise SettingsError("配置项 max_retries 不能为负数")
    if name == "max_tokens" and out is not None and out <= 0:
        raise SettingsError("配置项 max_tokens 必须大于 0")
    return out


def load_settings(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> RatingSettings:
    env = os.environ if env is None else env
    section = _read_file(path or settings_path(env)).get(SECTION)
    values: dict[str, Any] = dict(section) if isinstance(section, dict) else {}
    for name in _CASTS:
        ev = env.get(ENV_PREFIX + name.upper())
        if ev is not None and ev != "":
            values[name] = ev
    clean = {k: _coerce(k, v) for k, v in values.items() if k in _CASTS}
    return replace(RatingSettings(), **clean)


def save_settings(
    updates: Mapping[str, Any], path: Path | None = None, env: Mapping[str, str] | None = None
) -> Path:
    """合并写入文件里的 rating 段。api_key 传 None 表示保持原值，传 "" 表示清除。"""
    target = path or settings_path(env)
    data = _read_file(target)
    section = data.get(SECTION) if isinstance(data.get(SECTION), dict) else {}
    section = dict(section)
    for k, v in updates.items():
        if k not in _CASTS:
            raise SettingsError(f"未知配置项 {k}")
        if k == "api_key" and v is None:
            continue
        section[k] = _coerce(k, v)
    data[SECTION] = section
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target
