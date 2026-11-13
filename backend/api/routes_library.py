"""来源、分类、卡列表/详情/保存、图片、封面主色、变更通知。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.card import CardParseError, read_image_bytes

from . import cards
from .color import cached_color
from .state import ApiProblem, AppState, scan_to_dict

router = APIRouter(prefix="/api")
MAX_COLLECTION_NAME = 24


def get_state(request: Request) -> AppState:
    return request.app.state.qml


class SourceBody(BaseModel):
    path: str


class NameBody(BaseModel):
    name: str


class FavoriteBody(BaseModel):
    value: bool


class CollectionsBody(BaseModel):
    ids: list[int]


class SaveBody(BaseModel):
    # 上次读到的 meta.mtime_ns（字符串或整数）和/或 meta.hash，至少给一个
    expected_mtime_ns: int | str | None = None
    expected_hash: str | None = None
    fields: dict[str, Any]


# ---------------------------------------------------------------- 卡库
def library_info(state: AppState) -> dict[str, Any]:
    lib = state.lib
    return {
        "open": lib is not None,
        "opening": state.opening,
        "error": state.open_error,
        "data_dir": str(state.data_dir),
        "source_count": len(lib.sources) if lib else len(state.configured_sources()),
        "card_count": lib.db.unique_count() if lib and lib.db else 0,
        "watching": lib is not None,  # open_library 成功即已启动监听
        "last_scan": state.last_scan,
        "version": state.feed.version,
    }


@router.get("/library")
def get_library(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return library_info(state)


@router.post("/library/scan")
def scan_library(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {"scan": state.rescan(), "card_count": state.need_lib().db.unique_count()}


@router.post("/library/clear")
def clear_library(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """清空扫描出来的数据（索引、缩略图、封面色缓存）。来源列表、评分、卡文件都不动。"""
    return {"cleared": state.clear_library(), "card_count": 0}


# ---------------------------------------------------------------- 来源与分类
def _source_dict(state: AppState, path: str) -> dict[str, Any] | None:
    return next((s for s in state.need_lib().list_sources() if s["path"] == path), None)


@router.get("/sources")
def list_sources(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {"sources": state.need_lib().list_sources()}


@router.post("/sources", status_code=201)
def add_source(body: SourceBody, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """把文件夹或单张卡的原路径加入来源并原地索引，不复制文件。已在卡库里返回 409；
    新来源是现有来源的父文件夹时，子来源并入它，被并入的列在 merged。"""
    if not body.path.strip():
        raise ApiProblem(400, "bad_path", "路径不能为空")
    res = state.add_source(body.path.strip())
    return {
        "source": _source_dict(state, res.source.path),
        "merged": [s.path for s in res.merged],
        "scan": scan_to_dict(res.scan),
        "card_count": state.need_lib().db.unique_count(),
    }


@router.delete("/sources")
def remove_source(path: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """只把来源移出索引，不删任何文件。path 用查询参数，免得路径里的斜杠被路由吃掉。"""
    removed = state.remove_source(path)
    return {"removed": removed.path, "card_count": state.need_lib().db.unique_count()}


@router.get("/categories")
def categories(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """首页分类条：全部、收藏、未分类，后面跟用户自己建的分类（按创建顺序）。"""
    return state.need_lib().categories()


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name or len(name) > MAX_COLLECTION_NAME:
        raise ApiProblem(400, "bad_name", f"分类名要 1~{MAX_COLLECTION_NAME} 个字")
    return name


@router.post("/collections", status_code=201)
def create_collection(body: NameBody, state: AppState = Depends(get_state)) -> dict[str, Any]:
    lib = state.need_lib()
    try:
        res = lib.create_collection(_clean_name(body.name))
    except ValueError:
        raise ApiProblem(409, "name_exists", "已经有同名的分类") from None
    state.feed.push("shelf")
    return res


@router.patch("/collections/{collection_id}")
def rename_collection(
    collection_id: int, body: NameBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    lib = state.need_lib()
    name = _clean_name(body.name)
    try:
        found = lib.rename_collection(collection_id, name)
    except ValueError:
        raise ApiProblem(409, "name_exists", "已经有同名的分类") from None
    if not found:
        raise ApiProblem(404, "collection_not_found", "没有这个分类")
    state.feed.push("shelf")
    return {"id": collection_id, "name": name}


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """只删分类本身，卡和卡文件都不动。"""
    if not state.need_lib().delete_collection(collection_id):
        raise ApiProblem(404, "collection_not_found", "没有这个分类")
    state.feed.push("shelf")
    return {"deleted": collection_id}


# ---------------------------------------------------------------- 卡
@router.get("/cards")
def list_cards(
    q: str = "",
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: str = "name",
    order: str = Query("asc", pattern="^(asc|desc)$"),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    """category 缺省为全部（内容相同的卡只出一张）；取值是 /api/categories 的 key：favorites、unsorted、c<分类id>。"""
    lib = state.need_lib()
    q = q.strip()
    try:
        if q:
            result = lib.search(q, category=category, page=page, page_size=page_size)
        else:
            result = lib.list_cards(category, page=page, page_size=page_size, sort=sort, order=order)
    except ValueError as e:
        raise ApiProblem(400, "bad_query", str(e)) from None
    return {
        "items": [cards.public_row(lib, r) for r in result.items],
        "total": result.total, "page": result.page, "page_size": result.page_size,
    }


@router.get("/cards/{card_id}")
def get_card(card_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    lib = state.need_lib()
    return cards.build_detail(state, cards.row_by_id(lib, card_id))


@router.put("/cards/{card_id}")
def save_card(card_id: int, body: SaveBody, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """直接写回源文件（不备份）。冲突返回 409；WebP 卡会存成同名 PNG 并删除原 WebP，响应里的 id/path 是新的。"""
    return cards.save_card_fields(
        state, card_id, body.fields, body.expected_mtime_ns, body.expected_hash
    )


@router.put("/cards/{card_id}/favorite")
def set_favorite(card_id: int, body: FavoriteBody, state: AppState = Depends(get_state)) -> dict[str, Any]:
    lib = state.need_lib()
    row = cards.row_by_id(lib, card_id)
    lib.set_favorite(row, body.value)
    state.feed.push("shelf", card_id=card_id)
    return lib.db.card_shelf(row["path"])


@router.put("/cards/{card_id}/collections")
def set_card_collections(
    card_id: int, body: CollectionsBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """把这张卡的用户分类整体设为 ids（一张卡可同时在多个分类里）。"""
    lib = state.need_lib()
    row = cards.row_by_id(lib, card_id)
    lib.set_card_collections(row, body.ids)
    state.feed.push("shelf", card_id=card_id)
    return lib.db.card_shelf(row["path"])


# ---------------------------------------------------------------- 图片
@router.get("/thumb")
def thumbnail(path: str, state: AppState = Depends(get_state)) -> FileResponse:
    lib = state.need_lib()
    row = cards.row_by_path(lib, path)
    thumb = _thumb_path(lib, row)
    return FileResponse(thumb, media_type="image/webp", headers={"Cache-Control": "no-cache"})


def _thumb_path(lib: Any, row: dict[str, Any]):
    try:
        thumb = lib.get_thumbnail(row["id"])
    except Exception:  # noqa: BLE001  图片损坏等
        thumb = None
    if thumb is None:
        raise ApiProblem(404, "no_image", "这张卡没有可用的图片")
    return thumb


@router.get("/image")
def original_image(path: str, state: AppState = Depends(get_state)) -> Response:
    lib = state.need_lib()
    row = cards.row_by_path(lib, path)
    try:
        blob = read_image_bytes(lib.abs_path(row["path"]))
    except (CardParseError, OSError):
        blob = None
    if blob is None:
        raise ApiProblem(404, "no_image", "这张卡没有可用的图片")
    mime = "image/png" if blob[:4] == b"\x89PNG" else "image/webp"
    return Response(blob, media_type=mime, headers={"Cache-Control": "no-cache"})


@router.get("/color")
def cover_color(path: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """封面主色，'#rrggbb'；没有图片的卡返回 null。"""
    lib = state.need_lib()
    row = cards.row_by_path(lib, path)
    try:
        thumb = _thumb_path(lib, row)
        color = cached_color(lib.colors_dir, row["hash"], thumb)
    except (ApiProblem, OSError, ValueError):
        color = None
    return {"path": row["path"], "color": color}


# ---------------------------------------------------------------- 变更通知
@router.get("/changes")
def changes(
    since: int = Query(0, ge=0),
    wait: float = Query(0, ge=0, le=30),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    """前端带上次拿到的 version 轮询。wait>0 时若暂无新变更则挂起至多 wait 秒。
    reset=true 表示增量已不完整，应整体刷新。"""
    return state.feed.since(since, wait)
