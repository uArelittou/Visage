"""FastAPI 应用工厂。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from backend.rating.llm import ChatClient

from . import routes_library, routes_rating
from .placeholder import PLACEHOLDER_HTML
from .security import install_local_only
from .state import ApiProblem, AppState


class SPAStaticFiles(StaticFiles):
    """找不到的非 /api 路径回落到 index.html，支持前端 history 路由。"""

    async def get_response(self, path: str, scope: Any):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # Windows 下 StaticFiles 传进来的 path 用反斜杠
            if e.status_code == 404 and not path.replace("\\", "/").startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


def create_app(
    *,
    config_path: Path | None = None,
    frontend_dist: Path | None = None,
    rating_client: ChatClient | None = None,
    watch_debounce: float = 0.5,
    restore_library: bool = True,
) -> FastAPI:
    """config_path：用户配置文件（评分 API 与来源列表），缺省为用户数据目录下的 config.json；
    索引库、缩略图等数据放在它所在的目录。
    rating_client：注入后评分不再读 API 配置、不联网（测试用）。"""
    state = AppState(config_path=config_path, rating_client=rating_client, debounce=watch_debounce)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if restore_library:
            state.restore_library_async()
        yield
        state.close()

    app = FastAPI(title="千面录", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.qml = state
    install_local_only(app)

    @app.exception_handler(ApiProblem)
    async def _problem(_: Request, e: ApiProblem) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": e.code, "message": e.message, **e.extra}}, status_code=e.status
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError) -> JSONResponse:
        # 默认响应会回显 input，请求体里可能有 API Key，这里只留位置和原因
        errors = [{"loc": list(x["loc"]), "msg": x["msg"], "type": x["type"]} for x in e.errors()]
        return JSONResponse(
            {"detail": {"code": "validation_error", "message": "请求参数不合法", "errors": errors}},
            status_code=422,
        )

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(routes_library.router)
    app.include_router(routes_rating.router)

    if frontend_dist is not None and (Path(frontend_dist) / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def placeholder() -> str:
            return PLACEHOLDER_HTML

    return app
