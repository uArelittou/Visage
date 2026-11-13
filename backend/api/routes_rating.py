"""评分读写、后台 AI 评分、评分模型设置。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.rating.service import CardNotFoundError, RatingError
from backend.rating.settings import SettingsError, mask_secret

from .routes_library import get_state
from .state import ApiProblem, AppState

router = APIRouter(prefix="/api")
_NULLABLE = {"temperature", "max_tokens"}


class UserTotalBody(BaseModel):
    total: float


class RatingSettingsBody(BaseModel):
    """只改传了的字段。api_key：不传=保持原值，空字符串=清除。"""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout: float | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_retries: int | None = None
    context_char_budget: int | None = None


# ---------------------------------------------------------------- 评分
@router.get("/cards/{card_id}/rating")
def get_rating(card_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    svc = state.need_rating()
    try:
        return svc.get_rating(card_id)
    except CardNotFoundError as e:
        raise ApiProblem(404, "card_not_found", str(e)) from None


@router.post("/cards/{card_id}/rating/ai", status_code=202)
def start_ai_rating(card_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """启动后台 AI 评分，立即返回；用 GET 同路径查进度。"""
    return state.start_rating(card_id).to_dict()


@router.get("/cards/{card_id}/rating/ai")
def ai_rating_status(card_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    job = state.rating_job(card_id)
    return job.to_dict() if job else {"card_id": card_id, "state": "idle"}


@router.put("/cards/{card_id}/rating/user")
def set_user_total(
    card_id: int, body: UserTotalBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    svc = state.need_rating()
    try:
        result = svc.set_user_total(card_id, body.total)
    except CardNotFoundError as e:
        raise ApiProblem(404, "card_not_found", str(e)) from None
    except ValueError as e:
        raise ApiProblem(400, "bad_total", str(e)) from None
    state.feed.push("rating", card_id=card_id, state="user_total")
    return result


@router.delete("/cards/{card_id}/rating/user")
def clear_user_total(card_id: int, state: AppState = Depends(get_state)) -> dict[str, Any]:
    svc = state.need_rating()
    try:
        result = svc.clear_user_total(card_id)
    except RatingError as e:
        raise ApiProblem(404, "card_not_found", str(e)) from None
    state.feed.push("rating", card_id=card_id, state="user_total")
    return result


# ---------------------------------------------------------------- 设置
def settings_view(state: AppState) -> dict[str, Any]:
    """密钥只给「是否已设置」和打码后的形式，绝不返回明文。"""
    s = state.rating_settings()
    view = s.masked()
    view["configured"] = s.configured
    view["missing"] = s.missing()
    return view


@router.get("/settings/rating")
def get_rating_settings(state: AppState = Depends(get_state)) -> dict[str, Any]:
    try:
        return settings_view(state)
    except SettingsError as e:
        raise ApiProblem(400, "bad_settings", str(e)) from None


@router.put("/settings/rating")
def put_rating_settings(
    body: RatingSettingsBody, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    # null 只对「可为空」的项有意义（temperature=不传给模型）；其余项传 null 视为没改，不当作清空
    for name in [k for k, v in updates.items() if v is None and k not in _NULLABLE]:
        del updates[name]
    key = updates.get("api_key")
    # 前端把 GET 到的打码值原样回传时，当作「没改」，防止把真密钥覆盖成星号
    if key is not None and key and key == mask_secret(state.rating_settings().api_key):
        updates.pop("api_key")
    try:
        state.update_rating_settings(updates)
        return settings_view(state)
    except SettingsError as e:
        raise ApiProblem(400, "bad_settings", str(e)) from None
