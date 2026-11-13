import json
import os

import pytest
from api_helpers import make_client, wait_until

from backend.api import create_app
from backend.api.color import dominant_color
from PIL import Image


# ------------------------------------------------------------------ 卡库
def test_health_and_library_before_open(bare_client):
    client, _ = bare_client
    assert client.get("/api/health").json() == {"ok": True}
    info = client.get("/api/library").json()
    assert info["open"] is False and info["source_count"] == 0 and info["card_count"] == 0
    for url in ("/api/categories", "/api/sources", "/api/cards", "/api/cards/1", "/api/thumb?path=a.png"):
        r = client.get(url)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "no_library", url
    assert client.post("/api/library/scan").status_code == 409
    assert client.post("/api/library/clear").status_code == 409


def test_add_source_indexes_in_place_and_reports(env):
    info = env.client.get("/api/library").json()
    assert info["open"] and info["watching"] and info["card_count"] == 5 and info["source_count"] == 1
    scan = info["last_scan"]
    assert scan["added"] == 5 and scan["broken"] == 1
    assert scan["errors"][0]["path"] == env.path("bad.png")
    src = env.client.get("/api/sources").json()["sources"]
    assert [(s["path"], s["kind"], s["count"], s["missing"]) for s in src] == [
        (env.root.as_posix(), "folder", 5, False)]


def test_data_lives_in_user_dir_not_in_card_folder(env):
    env.client.get("/api/thumb", params={"path": env.path("hero.png")})
    env.client.get("/api/color", params={"path": env.path("hero.png")})
    home = env.config.parent
    assert (home / "library.db").is_file() and (home / "thumbs").is_dir() and (home / "colors").is_dir()
    assert not any(p.name.startswith(".kabao") for p in env.root.rglob("*"))
    assert sorted(p.name for p in env.root.iterdir()) == ["bad.png", "hero.png", "sub", "webcard.webp"]


def test_add_source_rejects_bad_paths(env, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    cases = {str(tmp_path / "nope"): "path_not_found", str(f): "bad_ext", "  ": "bad_path"}
    for path, code in cases.items():
        r = env.client.post("/api/sources", json={"path": path})
        assert r.status_code == 400 and r.json()["detail"]["code"] == code, path
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image at all")
    r = env.client.post("/api/sources", json={"path": str(junk)})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_a_card"
    assert env.client.get("/api/library").json()["source_count"] == 1


def test_rescan_picks_up_new_and_removed_files(env):
    (env.root / "new.png").write_bytes(env.mk.card_png(env.mk.V1_CARD, seed=4))
    (env.root / "bad.png").unlink()
    r = env.client.post("/api/library/scan")  # 监听线程可能已先处理，所以不断言具体的增删数
    assert r.status_code == 200 and "added" in r.json()["scan"]
    names = {i["path"] for i in env.client.get("/api/cards", params={"page_size": 500}).json()["items"]}
    assert env.path("new.png") in names and env.path("bad.png") not in names


def test_sources_persisted_and_restored(env):
    cfg = json.loads(env.config.read_text(encoding="utf-8"))
    assert cfg["library"]["sources"] == [env.root.as_posix()] and "root" not in cfg["library"]
    app = create_app(config_path=env.config, watch_debounce=0.1)
    with make_client(app) as c2:
        info = wait_until(lambda: (i := c2.get("/api/library").json())["open"] and i)
        assert info["card_count"] == 5 and info["source_count"] == 1


def test_legacy_single_root_config_is_used_as_one_folder_source(tmp_path, mk):
    from api_helpers import build_library

    root = tmp_path / "old"
    build_library(root, mk)
    cfg = tmp_path / "home" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"library": {"root": str(root)}}), encoding="utf-8")
    with make_client(create_app(config_path=cfg)) as c:
        info = wait_until(lambda: (i := c.get("/api/library").json())["open"] and i and i["card_count"] and i)
        assert info["card_count"] == 5 and info["source_count"] == 1


def test_missing_source_is_listed_not_fatal(tmp_path):
    cfg = tmp_path / "home" / "config.json"
    cfg.parent.mkdir(parents=True)
    gone = tmp_path / "gone"
    cfg.write_text(json.dumps({"library": {"sources": [str(gone)]}}), encoding="utf-8")
    with make_client(create_app(config_path=cfg)) as c:
        wait_until(lambda: c.get("/api/library").json()["open"])
        src = c.get("/api/sources").json()["sources"]
        assert len(src) == 1 and src[0]["missing"] is True and src[0]["count"] == 0
        assert c.delete("/api/sources", params={"path": str(gone)}).status_code == 200
        assert c.get("/api/sources").json()["sources"] == []


def test_adding_source_keeps_other_config_sections(env):
    env.client.put("/api/settings/rating", json={"model": "m1"})
    other = env.root.parent / "other.json"
    other.write_text(json.dumps(env.mk.V3_CARD, ensure_ascii=False), encoding="utf-8")
    assert env.client.post("/api/sources", json={"path": str(other)}).status_code == 201
    cfg = json.loads(env.config.read_text(encoding="utf-8"))
    assert cfg["rating"]["model"] == "m1" and len(cfg["library"]["sources"]) == 2


def test_old_import_endpoint_is_gone(env):
    r = env.client.post("/api/import", params={"name": "x.png"}, content=b"x")
    assert r.status_code in (404, 405)
    assert env.client.put("/api/library", json={"root": str(env.root)}).status_code in (404, 405)


# ------------------------------------------------------------------ 列表
def test_list_all_and_paths_are_absolute(env):
    r = env.client.get("/api/cards", params={"page_size": 500})
    items = r.json()["items"]
    assert r.json()["total"] == 5
    paths = {i["path"] for i in items}
    assert paths == {env.path(p) for p in ("hero.png", "webcard.webp", "bad.png", "sub/second.json", "sub/deep/third.png")}
    deep = env.card("sub/deep/third.png")
    assert deep["source"] == env.root.as_posix() and deep["sub"] == "sub/deep"


def test_list_pagination_sort_and_row_shape(env):
    r = env.client.get("/api/cards", params={"page_size": 2, "page": 2,
                                             "sort": "file_name", "order": "desc"})
    body = r.json()
    assert body["total"] == 5 and body["page"] == 2 and body["page_size"] == 2 and len(body["items"]) == 2
    row = body["items"][0]
    assert isinstance(row["mtime_ns"], str) and int(row["mtime_ns"]) > 0  # 字符串，避免 JS 丢精度
    assert {"id", "path", "name", "tags", "greeting_count", "display_score", "ai_total",
            "user_total", "is_broken", "favorite", "collections"} <= set(row)
    assert env.client.get("/api/cards", params={"sort": "evil; drop"}).status_code == 400
    assert env.client.get("/api/cards", params={"page_size": 9999}).status_code == 422
    assert env.client.get("/api/cards", params={"category": "nope"}).status_code == 400


def test_search_uses_fts(env):
    def search(q, **kw):
        r = env.client.get("/api/cards", params={"q": q, **kw})
        assert r.status_code == 200, r.text
        return {i["path"] for i in r.json()["items"]}

    both = {env.path("hero.png"), env.path("webcard.webp")}
    assert search("二号机") == both  # ≥3 字符走 FTS
    assert search("机器人") == both  # 标签
    assert search("启动完毕") == both  # 开场白
    assert search("三号") == {env.path("sub/second.json"), env.path("sub/deep/third.png")}  # 2 字符走 LIKE
    assert search("zzzz不存在") == set()
    assert search('"; DROP TABLE cards; --') == set()
    assert env.client.get("/api/library").json()["card_count"] == 5


# ------------------------------------------------------------------ 图片
def test_thumbnail_and_original_image(env):
    t = env.client.get("/api/thumb", params={"path": env.path("hero.png")})
    assert t.status_code == 200 and t.headers["content-type"] == "image/webp"
    assert t.content[:4] == b"RIFF"
    assert (env.config.parent / "thumbs").is_dir()

    o = env.client.get("/api/image", params={"path": env.path("hero.png")})
    assert o.status_code == 200 and o.headers["content-type"] == "image/png"
    assert o.content == (env.root / "hero.png").read_bytes()

    w = env.client.get("/api/image", params={"path": env.path("webcard.webp")})
    assert w.status_code == 200 and w.headers["content-type"] == "image/webp"
    assert env.client.get("/api/thumb", params={"path": env.path("sub/deep/third.png")}).status_code == 200


def test_json_and_broken_cards_have_no_image(env):
    for ep in ("/api/thumb", "/api/image"):
        assert env.client.get(ep, params={"path": env.path("sub/second.json")}).status_code == 404
    # 解析失败的卡不生成缩略图（原图字节照给，由浏览器自己决定能不能显示）
    assert env.client.get("/api/thumb", params={"path": env.path("bad.png")}).status_code == 404
    assert env.client.get("/api/color", params={"path": env.path("sub/second.json")}).json()["color"] is None


def test_unknown_path_is_404(env):
    assert env.client.get("/api/thumb", params={"path": env.path("nope.png")}).status_code == 404


@pytest.mark.parametrize("evil", [
    "../secret.png", "sub/../../secret.png", "..\\secret.png", "sub\\..\\..\\secret.png",
    "%2e%2e/secret.png", "/secret.png", "C:/Windows/win.ini", "C:\\Windows\\win.ini",
    "sub//second.json", "./hero.png", "sub/./second.json", "", "hero.png/",
    ".kabao/library.db", ".KABAO/library.db", "hero.png\x00.txt",
])
def test_path_traversal_rejected(env, evil):
    for ep in ("/api/thumb", "/api/image", "/api/color"):
        r = env.client.get(ep, params={"path": evil})
        assert r.status_code in (400, 404, 422), (ep, evil, r.status_code)
        assert r.content[:4] not in (b"RIFF", b"\x89PNG"), (ep, evil)


def test_absolute_path_to_outside_file_rejected(env):
    for ep in ("/api/thumb", "/api/image"):
        r = env.client.get(ep, params={"path": str(env.outside)})
        assert r.status_code in (400, 404)
        r = env.client.get(ep, params={"path": env.outside.as_posix()})
        assert r.status_code in (400, 404)
        assert r.content[:4] not in (b"RIFF", b"\x89PNG")


def test_raw_url_traversal_rejected(env):
    # 绕过 TestClient 的参数编码，直接发带 .. 的原始查询串
    for q in ("path=../secret.png", "path=..%2Fsecret.png", "path=%2e%2e%5csecret.png"):
        r = env.client.get("/api/image?" + q)
        assert r.status_code in (400, 404), q


def test_symlink_pointing_outside_is_not_served(env):
    link = env.root / "link.png"
    try:
        os.symlink(env.outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不能创建符号链接")
    env.client.post("/api/library/scan")
    for ep in ("/api/thumb", "/api/image"):
        r = env.client.get(ep, params={"path": env.path("link.png")})
        assert r.status_code in (400, 404)
        assert r.content != env.outside.read_bytes()


def test_junction_pointing_outside_is_not_served(env, tmp_path):
    """Windows 目录联接（无需管理员权限）：扫描器会走进去并入库，但接口不能读到来源目录外的文件。"""
    import subprocess
    import sys

    if sys.platform != "win32":
        pytest.skip("仅 Windows")
    ext_dir = tmp_path / "elsewhere"
    ext_dir.mkdir()
    (ext_dir / "leak.png").write_bytes(env.mk.card_png(env.mk.V1_CARD, seed=11))
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(env.root / "jn"), str(ext_dir)],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("无法创建目录联接")
    try:
        env.client.post("/api/library/scan")
        for ep in ("/api/thumb", "/api/image", "/api/color"):
            resp = env.client.get(ep, params={"path": env.path("jn/leak.png")})
            assert resp.status_code in (400, 404), (ep, resp.status_code)
            assert resp.content[:4] not in (b"RIFF", b"\x89PNG")
        card = [i for i in env.client.get("/api/cards", params={"page_size": 500}).json()["items"]
                if i["path"] == env.path("jn/leak.png")]
        for item in card:  # 即使被扫描器索引了，详情和保存也不能碰库外的文件
            assert env.client.get(f"/api/cards/{item['id']}").status_code == 400
            r = env.client.put(f"/api/cards/{item['id']}", json={
                "fields": {"name": "x"}, "expected_hash": "0" * 64})
            assert r.status_code == 400
        assert (ext_dir / "leak.png").read_bytes() == env.mk.card_png(env.mk.V1_CARD, seed=11)
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(env.root / "jn")], capture_output=True)  # 只删联接本身


def test_cover_color_is_computed_and_cached(env):
    r = env.client.get("/api/color", params={"path": env.path("hero.png")})
    color = r.json()["color"]
    assert r.status_code == 200 and len(color) == 7 and color.startswith("#")
    int(color[1:], 16)
    cache = list((env.config.parent / "colors").glob("*.txt"))
    assert len(cache) == 1
    cache[0].write_text("#123456", encoding="ascii")
    assert env.client.get("/api/color", params={"path": env.path("hero.png")}).json()["color"] == "#123456"


def test_dominant_color_prefers_saturated_over_background():
    im = Image.new("RGB", (40, 40), (10, 10, 10))
    im.paste((200, 30, 30), (0, 0, 14, 14))
    assert dominant_color(im) == "#c81e1e"
    solid = Image.new("RGB", (8, 8), (30, 90, 200))
    assert dominant_color(solid) == "#1e5ac8"
    assert dominant_color(Image.new("RGBA", (8, 8), (0, 0, 0, 0))) is None


# ------------------------------------------------------------------ 变更通知
def test_changes_feed_reports_watcher_events(env):
    v0 = env.client.get("/api/changes").json()["version"]
    (env.root / "dropped.png").write_bytes(env.mk.card_png(env.mk.V1_CARD, seed=7))

    def seen():
        body = env.client.get("/api/changes", params={"since": v0, "wait": 1}).json()
        hits = [c for c in body["changes"] if c["kind"] == "watch" and env.path("dropped.png") in c["upserted"]]
        return body if hits else None

    body = wait_until(seen)
    assert body["version"] > v0 and body["reset"] is False
    # 已经是最新版本时，wait=0 立即返回空
    again = env.client.get("/api/changes", params={"since": body["version"]}).json()
    assert again["changes"] == [] and again["reset"] is False

    (env.root / "dropped.png").unlink()
    wait_until(lambda: any(
        c["kind"] == "watch" and env.path("dropped.png") in c["removed"]
        for c in env.client.get("/api/changes", params={"since": body["version"], "wait": 1}).json()["changes"]
    ))


def test_changes_reset_when_client_is_ahead_or_far_behind(env):
    assert env.client.get("/api/changes", params={"since": 10**6}).json()["reset"] is True
    for _ in range(250):
        env.client.app.state.qml.feed.push("noise")
    assert env.client.get("/api/changes", params={"since": 0}).json()["reset"] is True


def test_changes_long_poll_wakes_on_push(env):
    import threading
    import time

    v = env.client.get("/api/changes").json()["version"]
    threading.Timer(0.2, lambda: env.client.app.state.qml.feed.push("ping")).start()
    t0 = time.monotonic()
    body = env.client.get("/api/changes", params={"since": v, "wait": 5}).json()
    assert [c["kind"] for c in body["changes"]] == ["ping"] and time.monotonic() - t0 < 4
