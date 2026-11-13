"""本地接口的访问限制：只认回环地址的 Host 和 Origin。

接口监听在 127.0.0.1，但用户浏览器里别的网站仍能向 127.0.0.1 发请求（或借 DNS 重绑定把域名指过来）。
校验 Host 挡重绑定，校验 Origin 挡跨站请求。
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _host_of(value: str) -> str:
    # Host 头形如 "127.0.0.1:8000" 或 "[::1]:8000"
    return urlsplit("//" + value).hostname or ""


def install_local_only(app: FastAPI) -> None:
    @app.middleware("http")
    async def local_only(request: Request, call_next):  # noqa: ANN001
        host = _host_of(request.headers.get("host", ""))
        if host.lower() not in LOOPBACK_HOSTS:
            return _deny("Host 不是本机地址")
        origin = request.headers.get("origin")
        if origin is not None and (urlsplit(origin).hostname or "").lower() not in LOOPBACK_HOSTS:
            return _deny("不接受来自其他站点的请求")
        return await call_next(request)


def _deny(message: str) -> JSONResponse:
    return JSONResponse({"detail": {"code": "forbidden_origin", "message": message}}, status_code=403)
