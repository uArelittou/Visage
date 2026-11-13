import socket

import httpx
import pytest
from api_helpers import make_client

import app as desktop
from backend.api import create_app


# ------------------------------------------------------------------ 本机访问限制
def test_non_loopback_host_is_rejected(env):
    r = env.client.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden_origin"
    assert env.client.get("/api/health", headers={"host": "localhost:5173"}).status_code == 200
    assert env.client.get("/api/health", headers={"host": "[::1]:8000"}).status_code == 200


def test_cross_site_origin_is_rejected(env):
    bad = env.client.put("/api/library", json={"root": str(env.root)},
                         headers={"origin": "https://evil.example.com"})
    assert bad.status_code == 403
    assert env.client.get("/api/health", headers={"origin": "null"}).status_code == 403
    ok = env.client.get("/api/health", headers={"origin": "http://localhost:5173"})
    assert ok.status_code == 200


# ------------------------------------------------------------------ 前端托管
def test_placeholder_page_when_no_dist(env):
    r = env.client.get("/")
    assert r.status_code == 200 and "后端已就绪" in r.text and "/api/library" in r.text
    r = env.client.get("/api/not-a-route")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_serves_frontend_dist_with_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>VUE-APP</html>", encoding="utf-8")
    (dist / "assets" / "a.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(config_path=tmp_path / "c.json", frontend_dist=dist, restore_library=False)
    with make_client(app) as c:
        assert "VUE-APP" in c.get("/").text
        assert c.get("/assets/a.js").text == "console.log(1)"
        assert "VUE-APP" in c.get("/some/route").text  # history 路由回落
        assert c.get("/api/health").json() == {"ok": True}
        r = c.get("/api/not-a-route")
        assert r.status_code == 404 and "VUE-APP" not in r.text


def test_dist_without_index_falls_back_to_placeholder(tmp_path):
    (tmp_path / "dist").mkdir()
    app = create_app(config_path=tmp_path / "c.json", frontend_dist=tmp_path / "dist", restore_library=False)
    with make_client(app) as c:
        assert "后端已就绪" in c.get("/").text


# ------------------------------------------------------------------ app.py 启动
def test_start_backend_binds_loopback_free_port():
    server, thread, port = desktop.start_backend(0)
    try:
        assert port > 0
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5)
        assert r.json() == {"ok": True}
        assert "后端已就绪" in httpx.get(f"http://127.0.0.1:{port}/", timeout=5).text \
            or (desktop.FRONTEND_DIST / "index.html").is_file()
        # 只绑回环：用本机其他地址连不上（没有其他地址时跳过这条断言）
        others = [a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                  if not a[4][0].startswith("127.")]
        if others:
            with pytest.raises(OSError):
                socket.create_connection((others[0], port), timeout=1).close()
    finally:
        desktop.stop_backend(server, thread)
    assert not thread.is_alive()


def test_start_backend_picks_distinct_ports():
    a = desktop.start_backend(0)
    b = desktop.start_backend(0)
    try:
        assert a[2] != b[2]
    finally:
        desktop.stop_backend(a[0], a[1])
        desktop.stop_backend(b[0], b[1])
