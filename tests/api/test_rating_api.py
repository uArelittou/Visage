import logging
import shutil

import pytest
from api_helpers import API_KEY, wait_until

from backend.rating.llm import LLMError


@pytest.fixture
def lin_id(env, lin):
    shutil.copy(lin.path, env.root / "lin.json")
    env.client.post("/api/library/scan")
    return env.card_id("lin.json")


def configure(env):
    r = env.client.put("/api/settings/rating", json={
        "base_url": "http://127.0.0.1:1/v1", "model": "fake-model", "api_key": API_KEY})
    assert r.status_code == 200, r.text


def run_job(env, cid):
    r = env.client.post(f"/api/cards/{cid}/rating/ai")
    assert r.status_code == 202, r.text
    return wait_until(lambda: (
        (s := env.client.get(f"/api/cards/{cid}/rating/ai").json())["state"] != "running" and s))


# ------------------------------------------------------------------ 读取与用户总分
def test_unrated_card(env):
    cid = env.card_id("hero.png")
    r = env.client.get(f"/api/cards/{cid}/rating").json()
    assert r["display_score"] is None and r["has_ai"] is False and r["result"] is None
    assert env.client.get(f"/api/cards/{cid}/rating/ai").json() == {"card_id": cid, "state": "idle"}
    assert env.client.get("/api/cards/99999/rating").status_code == 404


def test_user_total_set_clear_and_validation(env):
    cid = env.card_id("hero.png")
    url = f"/api/cards/{cid}/rating/user"
    r = env.client.put(url, json={"total": 8.26})
    assert r.status_code == 200
    body = r.json()
    assert body["user_total"] == 8.3 and body["display_score"] == 8.3 and body["user_rated_at"]
    assert env.card("hero.png")["user_total"] == 8.3 and env.card("hero.png")["display_score"] == 8.3
    for bad in (-1, 10.5, "abc", None):
        assert env.client.put(url, json={"total": bad}).status_code in (400, 422), bad
    assert env.client.put(url, json={}).status_code == 422
    assert env.client.put("/api/cards/99999/rating/user", json={"total": 5}).status_code == 404

    cleared = env.client.delete(url).json()
    assert cleared["user_total"] is None and cleared["display_score"] is None
    assert env.client.delete("/api/cards/99999/rating/user").status_code == 404


# ------------------------------------------------------------------ AI 评分
def test_ai_rating_runs_in_background_and_stores_result(env, lin, lin_id):
    gate = {}

    def handler(messages, n):
        gate["called"] = True
        return lin.output

    env.fake.handler = handler
    r = env.client.post(f"/api/cards/{lin_id}/rating/ai")
    assert r.status_code == 202 and r.json()["state"] in ("running", "done")
    status = wait_until(lambda: (
        (s := env.client.get(f"/api/cards/{lin_id}/rating/ai").json())["state"] != "running" and s))
    assert status["state"] == "done" and status["error"] is None and gate["called"]

    rating = env.client.get(f"/api/cards/{lin_id}/rating").json()
    assert rating["ai_total"] == 8.0 and rating["display_score"] == 8.0 and rating["has_ai"]
    assert rating["model"] == "fake-model" and rating["rubric_version"] == 2
    res = rating["result"]
    assert res["dimensions"]["character"]["score"] == 9
    assert res["review"] == lin.output["review"]
    assert res["opening"]["count_score"] == 3 and "items" in res["bonus"] and "items" in res["deductions"]
    assert env.card("lin.json")["ai_total"] == 8.0


def test_post_does_not_block_on_slow_model(env, lin, lin_id):
    import threading

    release = threading.Event()

    def handler(messages, n):
        release.wait(10)
        return lin.output

    env.fake.handler = handler
    try:
        r = env.client.post(f"/api/cards/{lin_id}/rating/ai")
        assert r.status_code == 202
        assert env.client.get(f"/api/cards/{lin_id}/rating/ai").json()["state"] == "running"
        again = env.client.post(f"/api/cards/{lin_id}/rating/ai")
        assert again.status_code == 409 and again.json()["detail"]["code"] == "rating_busy"
        assert env.client.get("/api/health").status_code == 200  # 评分期间其他接口照常
    finally:
        release.set()
    assert wait_until(lambda: env.client.get(f"/api/cards/{lin_id}/rating/ai").json()["state"] == "done")


def test_ai_rating_keeps_user_total(env, lin, lin_id):
    env.fake.handler = lambda m, n: lin.output
    env.client.put(f"/api/cards/{lin_id}/rating/user", json={"total": 6})
    assert run_job(env, lin_id)["state"] == "done"
    r = env.client.get(f"/api/cards/{lin_id}/rating").json()
    assert r["user_total"] == 6 and r["ai_total"] == 8.0 and r["display_score"] == 6


def test_ai_rating_failure_is_reported_and_stores_nothing(env, lin_id):
    configure(env)
    env.fake.handler = lambda m, n: "这不是 JSON"
    s = run_job(env, lin_id)
    assert s["state"] == "failed" and s["error_type"] == "RatingFailed" and s["error"]
    assert env.fake.calls == 3  # 默认重试 2 次
    r = env.client.get(f"/api/cards/{lin_id}/rating").json()
    assert r["has_ai"] is False and r["ai_total"] is None


def test_ai_rating_error_message_never_contains_key(env, lin_id, caplog):
    configure(env)

    def boom(messages, n):
        raise LLMError(f"连接失败 Authorization: Bearer {API_KEY}", status=401)

    env.fake.handler = boom
    with caplog.at_level(logging.DEBUG):
        s = run_job(env, lin_id)
    assert s["state"] == "failed" and API_KEY not in str(s) and "***" in s["error"]
    assert API_KEY not in caplog.text


def test_ai_rating_unexpected_exception_hides_details(env, lin_id):
    configure(env)

    def boom(messages, n):
        raise RuntimeError(f"内部错误带着 {API_KEY}")

    env.fake.handler = boom
    s = run_job(env, lin_id)
    assert s["state"] == "failed" and s["error_type"] == "RuntimeError"
    assert API_KEY not in str(s)


def test_ai_rating_requires_config_when_no_client_injected(bare_client, tmp_path, mk):
    from api_helpers import build_library
    client, _ = bare_client
    root = tmp_path / "cards"
    build_library(root, mk)
    client.app.state.qml.open_library()
    client.post("/api/sources", json={"path": str(root)})
    cid = client.get("/api/cards").json()["items"][0]["id"]
    r = client.post(f"/api/cards/{cid}/rating/ai")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "rating_not_configured"
    assert "api_key" in r.json()["detail"]["message"] and "model" in r.json()["detail"]["message"]


def test_ai_rating_unknown_card_and_broken_card(env):
    assert env.client.post("/api/cards/99999/rating/ai").status_code == 404
    cid = env.card_id("bad.png")
    s = run_job(env, cid)
    assert s["state"] == "failed" and "无法解析" in s["error"]


def test_rating_endpoints_without_library(bare_client):
    client, _ = bare_client
    for method, url in (("get", "/api/cards/1/rating"), ("post", "/api/cards/1/rating/ai")):
        assert getattr(client, method)(url).status_code == 409


def test_rating_events_reach_changes_feed(env, lin, lin_id):
    env.fake.handler = lambda m, n: lin.output
    v0 = env.client.get("/api/changes").json()["version"]
    run_job(env, lin_id)
    wait_until(lambda: any(
        c["kind"] == "rating" and c["card_id"] == lin_id and c["state"] == "done"
        for c in env.client.get("/api/changes", params={"since": v0}).json()["changes"]))


# ------------------------------------------------------------------ 设置与密钥
def test_settings_default_is_unconfigured(env):
    s = env.client.get("/api/settings/rating").json()
    assert s["api_key_set"] is False and s["api_key"] == "" and s["configured"] is False
    assert set(s["missing"]) == {"base_url", "api_key", "model"}


def test_settings_roundtrip_never_returns_plaintext_key(env):
    r = env.client.put("/api/settings/rating", json={
        "base_url": "https://api.example.com/v1", "model": "gpt-x", "api_key": API_KEY, "timeout": 120})
    assert r.status_code == 200
    for resp in (r, env.client.get("/api/settings/rating")):
        assert API_KEY not in resp.text
        s = resp.json()
        assert s["api_key_set"] is True and s["configured"] is True
        assert s["base_url"] == "https://api.example.com/v1" and s["model"] == "gpt-x" and s["timeout"] == 120
        assert s["api_key"] and s["api_key"] != API_KEY and s["api_key"].endswith(API_KEY[-4:])
        assert API_KEY[3:-4] not in s["api_key"]


def test_short_key_is_fully_masked(env):
    env.client.put("/api/settings/rating", json={"api_key": "short-key"})
    s = env.client.get("/api/settings/rating").json()
    assert s["api_key_set"] and "short" not in s["api_key"] and "key" not in s["api_key"]


def test_partial_update_keeps_key_and_masked_echo_is_ignored(env):
    env.client.put("/api/settings/rating", json={"api_key": API_KEY, "model": "m1"})
    env.client.put("/api/settings/rating", json={"model": "m2"})  # 不传 api_key = 不动
    masked = env.client.get("/api/settings/rating").json()["api_key"]
    r = env.client.put("/api/settings/rating", json={"model": "m3", "api_key": masked})  # 前端原样回传打码值
    assert r.status_code == 200 and r.json()["model"] == "m3"
    app_state = env.client.app.state.qml
    assert app_state.rating_settings().api_key == API_KEY
    env.client.put("/api/settings/rating", json={"model": None})  # null 不清空必填项
    assert env.client.get("/api/settings/rating").json()["model"] == "m3"


def test_empty_string_clears_key(env):
    env.client.put("/api/settings/rating", json={"api_key": API_KEY})
    s = env.client.put("/api/settings/rating", json={"api_key": ""}).json()
    assert s["api_key_set"] is False and s["api_key"] == ""


def test_invalid_settings_rejected_without_echoing_key(env):
    r = env.client.put("/api/settings/rating", json={"api_key": API_KEY, "timeout": -5})
    assert r.status_code == 400 and API_KEY not in r.text
    r = env.client.put("/api/settings/rating", json={"api_key": API_KEY, "timeout": "abc"})
    assert r.status_code == 422 and API_KEY not in r.text
    assert "input" not in r.text
    r = env.client.put("/api/settings/rating", content=f'["{API_KEY}"]',
                       headers={"content-type": "application/json"})
    assert r.status_code == 422 and API_KEY not in r.text
    r = env.client.put("/api/settings/rating", content=f"{{bad json {API_KEY}",
                       headers={"content-type": "application/json"})
    assert r.status_code == 422 and API_KEY not in r.text
    # 失败的请求没有写入密钥
    assert env.client.get("/api/settings/rating").json()["api_key_set"] is False


def test_key_not_written_to_logs(env, caplog):
    with caplog.at_level(logging.DEBUG):
        env.client.put("/api/settings/rating", json={"api_key": API_KEY, "model": "m"})
        env.client.get("/api/settings/rating")
        env.client.put("/api/settings/rating", json={"api_key": API_KEY, "timeout": "abc"})
    assert API_KEY not in caplog.text


def test_settings_reach_the_rating_service(env, lin, lin_id):
    # 配置经接口写入后，评分服务读到的就是同一份
    configure(env)
    s = env.client.app.state.qml.rating_settings()
    assert (s.base_url, s.model, s.api_key) == ("http://127.0.0.1:1/v1", "fake-model", API_KEY)
