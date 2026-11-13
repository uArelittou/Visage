"""卡相关的接口逻辑：路径校验、详情序列化、带冲突检查的保存。

JSON 里的 mtime_ns 一律用字符串：纳秒时间戳约 1.7e18，超过 JS 的安全整数范围 2^53，用数字传会丢精度。
"""
from __future__ import annotations

import hashlib
from typing import Any

from backend.card import CardParseError, CardWriteError, save_card
from backend.library import Library
from backend.rating.blocks import greetings

from .state import ApiProblem, AppState

STR_FIELDS = (
    "name", "description", "personality", "scenario", "first_mes", "mes_example",
    "creator", "creator_notes", "character_version", "system_prompt",
    "post_history_instructions",
)
LIST_FIELDS = ("alternate_greetings", "tags")
EDITABLE = STR_FIELDS + LIST_FIELDS + ("character_book", "extensions")


# ---------------------------------------------------------------- 路径
def row_by_path(lib: Library, path: str) -> dict[str, Any]:
    """只返回已入库的卡：路径必须正是索引里记着的那一条，再确认它仍落在来源内（含符号链接）。"""
    if not path or "\x00" in path:
        raise ApiProblem(400, "bad_path", "非法路径")
    row = lib.get_card_by_path(path)
    if row is None:
        raise ApiProblem(404, "card_not_found", "卡库里没有这个文件")
    try:
        lib.abs_path(row["path"])
    except (ValueError, OSError):
        raise ApiProblem(400, "bad_path", "这张卡的文件不在来源范围内") from None
    return row


def row_by_id(lib: Library, card_id: int) -> dict[str, Any]:
    row = lib.get_card(card_id)
    if row is None:
        raise ApiProblem(404, "card_not_found", f"没有 id={card_id} 的卡")
    try:
        lib.abs_path(row["path"])
    except (ValueError, OSError):  # 目录联接/符号链接把文件指到了来源外
        raise ApiProblem(400, "bad_path", "这张卡的文件不在来源范围内") from None
    return row


# ---------------------------------------------------------------- 序列化
def public_row(lib: Library, row: dict[str, Any]) -> dict[str, Any]:
    """列表项：库里的一行 + 评分摘要；mtime_ns 转字符串。"""
    out = dict(row)
    out["mtime"] = out["mtime_ns"] / 1e9
    out["mtime_ns"] = str(out["mtime_ns"])
    rr = lib.db.get_rating_row(row["path"]) if lib.db else None
    ai = rr["ai_total"] if rr else None
    user = rr["user_total"] if rr else None
    out.update(ai_total=ai, user_total=user, display_score=user if user is not None else ai)
    out.update(lib.db.card_shelf(row["path"]) if lib.db else {"favorite": False, "collections": []})
    return out


def _book_payload(book: Any) -> dict | None:
    if not isinstance(book, dict):
        return None
    entries = book.get("entries")
    if isinstance(entries, dict):  # 非标准写法：以 uid 为键的对象，统一成数组给前端
        return {**book, "entries": list(entries.values())}
    return book


def card_payload(card: Any) -> dict[str, Any]:
    return {
        **{k: getattr(card, k) for k in STR_FIELDS},
        "spec": card.spec,
        "alternate_greetings": list(card.alternate_greetings),
        "tags": list(card.tags),
        # 编号与评分里的「开场白#N」一致：只给非空开场白连续编号
        "greetings": [{"index": g.index, "source": g.source, "text": g.text} for g in greetings(card)],
        "character_book": _book_payload(card.character_book),
        "regex_scripts": card.regex_scripts,
        "scripts": card.scripts,
        "extensions": card.extensions,
    }


def build_detail(state: AppState, row: dict[str, Any]) -> dict[str, Any]:
    """详情以磁盘为准（含 mtime/hash，供保存时做冲突检查），不信索引里可能过期的值。"""
    lib = state.need_lib()
    path = lib.abs_path(row["path"])
    try:
        st = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        raise ApiProblem(404, "file_missing", "文件已不存在，可能被移动或删除") from None
    card, error = None, ""
    try:
        card = state.loader(path)
    except Exception as e:  # noqa: BLE001  坏卡也要能返回元数据
        error = f"{type(e).__name__}: {e}"
    return {
        "id": row["id"], "path": row["path"], "source": row["source"], "sub": row["sub"],
        "file_name": row["file_name"], "ext": row["ext"],
        "meta": {
            "mtime_ns": str(st.st_mtime_ns), "mtime": st.st_mtime_ns / 1e9, "size": st.st_size,
            "hash": digest, "is_broken": card is None, "error": error,
        },
        "card": card_payload(card) if card is not None else None,
    }


# ---------------------------------------------------------------- 保存
def validate_fields(fields: dict[str, Any]) -> dict[str, Any]:
    for key, value in fields.items():
        if key not in EDITABLE:
            raise ApiProblem(400, "bad_field", f"不能编辑的字段: {key}")
        if not _type_ok(key, value):
            raise ApiProblem(400, "bad_field", f"字段类型不对: {key}")
    return fields


def _type_ok(key: str, value: Any) -> bool:
    if key in STR_FIELDS:
        return isinstance(value, str)
    if key in LIST_FIELDS:
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if key == "character_book":
        return value is None or isinstance(value, dict)
    return isinstance(value, dict)  # extensions


def parse_expected_mtime(value: int | str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiProblem(400, "bad_expected", "expected_mtime_ns 必须是整数或整数字符串") from None


def save_card_fields(
    state: AppState, card_id: int, fields: dict[str, Any],
    expected_mtime_ns: int | str | None, expected_hash: str | None,
) -> dict[str, Any]:
    lib = state.need_lib()
    changes = validate_fields(fields)
    mtime = parse_expected_mtime(expected_mtime_ns)
    if mtime is None and not expected_hash:
        raise ApiProblem(400, "missing_expected", "需要提供 expected_mtime_ns 或 expected_hash 用于冲突检查")
    row = row_by_id(lib, card_id)
    key = row["path"]
    path = lib.abs_path(key)

    with state.write_lock:
        # mtime 缺省时传 -1：必然与磁盘不等，转入按 hash 比较
        c = lib.check_conflict(key, -1 if mtime is None else mtime, expected_hash)
        if c.conflict:
            raise ApiProblem(
                409, "conflict", "文件在你打开之后被改动过" if c.reason == "modified" else "文件已不存在",
                reason=c.reason,
                current=None if c.current_hash is None else {
                    "mtime_ns": str(c.current_mtime_ns), "size": c.current_size, "hash": c.current_hash,
                },
            )
        try:
            card = state.loader(path)
        except Exception as e:  # noqa: BLE001
            raise ApiProblem(422, "card_unreadable", f"卡文件无法解析: {type(e).__name__}") from None
        for field_name, value in changes.items():
            setattr(card, field_name, value)
        # WebP 卡存为同名 PNG；目标已存在时 save_card 会拒绝，这里先判断，给出明确的错误码
        if path.suffix.lower() == ".webp" and path.with_suffix(".png").exists():
            raise ApiProblem(409, "target_exists", "同名 PNG 已存在，拒绝覆盖")
        old_rating = lib.db.get_rating_row(key)
        try:
            target = save_card(path, card)
        except CardParseError as e:
            raise ApiProblem(422, "card_unwritable", str(e)) from None
        except CardWriteError as e:
            raise ApiProblem(500, "write_failed", str(e)) from None
        new_key = target.as_posix()
        if new_key != key:
            # 单卡来源的文件换了名字，来源要跟过去，否则下次扫描会把它当成丢失
            state.replace_file_source(key, new_key)
        lib.refresh_file(key)
        if new_key != key:
            lib.refresh_file(new_key)
        new_row = lib.get_card_by_path(new_key)
        if new_row is None:
            raise ApiProblem(500, "write_failed", "保存后索引里找不到这张卡")
        if new_key != key and old_rating:
            _carry_rating(lib, new_key, new_row["hash"], old_rating)
    state.feed.push("saved", path=new_key, old_path=key, card_id=new_row["id"])
    return build_detail(state, new_row)


def _carry_rating(lib: Library, new_path: str, new_hash: str, old: dict[str, Any]) -> None:
    """WebP 转 PNG 后文件名变了、内容也变了，评分无法按路径或哈希自动接上，这里手动搬过去。"""
    if old["ai_result"] is not None and old["ai_total"] is not None:
        lib.db.save_ai_rating(
            new_path, new_hash, ai_total=old["ai_total"], ai_result=old["ai_result"],
            model=old["model"], rubric_version=old["rubric_version"],
        )
    if old["user_total"] is not None:
        lib.db.set_user_total(new_path, new_hash, old["user_total"])
