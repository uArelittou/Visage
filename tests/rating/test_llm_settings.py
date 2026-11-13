import json
import urllib.request

import pytest
from rating_helpers import FakeServer, ok_body

from backend.rating.llm import LLMError, OpenAIChatClient, chat_completions_url
from backend.rating.settings import (
    ENV_PREFIX, RatingSettings, SettingsError, load_settings, mask_secret, save_settings,
    settings_path, user_data_dir,
)

KEY = "sk-TEST-SECRET-0123456789abcdef"


def client_for(srv, **kw):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机测试不走系统代理
    return OpenAIChatClient(srv.url, KEY, "m-1", opener=opener.open, sleep=lambda s: None, **kw)


# ------------------------------------------------------------------ 客户端
def test_url_joining():
    assert chat_completions_url("https://a.b/v1") == "https://a.b/v1/chat/completions"
    assert chat_completions_url("https://a.b/v1/") == "https://a.b/v1/chat/completions"
    assert chat_completions_url("https://a.b/v1/chat/completions") == "https://a.b/v1/chat/completions"


def test_request_shape_and_response_parsing():
    with FakeServer([(200, ok_body("结果"))]) as srv:
        c = client_for(srv, temperature=0.3, max_tokens=999)
        r = c.complete([{"role": "user", "content": "hi"}])
    req = srv.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    assert req["body"] == {
        "model": "m-1", "messages": [{"role": "user", "content": "hi"}], "stream": False,
        "temperature": 0.3, "max_tokens": 999,
    }
    assert (r.text, r.finish_reason, r.model, r.usage) == ("结果", "stop", "m-1", {"total_tokens": 3})


def test_content_parts_and_optional_params():
    body = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}]}}]}).encode()
    with FakeServer([(200, body)]) as srv:
        c = client_for(srv, temperature=None)
        assert c.complete([]).text == "甲乙"
    assert "temperature" not in srv.requests[0]["body"] and "max_tokens" not in srv.requests[0]["body"]


def test_http_error_never_leaks_key():
    echo = lambda headers, body: json.dumps({"error": f"bad key {headers['Authorization']}"}).encode()  # noqa: E731
    with FakeServer([(401, echo)]) as srv:
        c = client_for(srv)
        with pytest.raises(LLMError) as ei:
            c.complete([{"role": "user", "content": "x"}])
    e = ei.value
    assert e.status == 401 and not e.retryable
    assert KEY not in str(e) and KEY not in repr(e) and KEY not in repr(c)
    assert "Bearer" not in str(e) or KEY not in str(e)
    assert e.__cause__ is None and (e.__context__ is None or KEY not in str(e.__context__))


def test_connection_error_never_leaks_key():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    c = OpenAIChatClient("http://127.0.0.1:1/v1?key=" + KEY, KEY, "m", opener=opener,
                         transient_retries=0, timeout=2)
    with pytest.raises(LLMError) as ei:
        c.complete([])
    assert KEY not in str(ei.value) and KEY not in repr(c)
    assert ei.value.retryable


def test_transient_errors_are_retried_then_succeed():
    with FakeServer([(503, b"busy"), (429, b"slow"), (200, ok_body("好"))]) as srv:
        c = client_for(srv, transient_retries=2)
        assert c.complete([]).text == "好"
        assert len(srv.requests) == 3


def test_retries_are_bounded_and_client_errors_not_retried():
    with FakeServer([(503, b"a"), (503, b"b"), (503, b"c")]) as srv:
        with pytest.raises(LLMError) as ei:
            client_for(srv, transient_retries=1).complete([])
        assert ei.value.status == 503 and len(srv.requests) == 2
    with FakeServer([(400, b"bad"), (200, ok_body())]) as srv:
        with pytest.raises(LLMError):
            client_for(srv, transient_retries=2).complete([])
        assert len(srv.requests) == 1


def test_non_chat_completions_reply():
    with FakeServer([(200, b'{"hello": 1}')]) as srv:
        with pytest.raises(LLMError, match="格式"):
            client_for(srv).complete([])


# ------------------------------------------------------------------ 配置
def test_defaults_and_roundtrip(tmp_path):
    env = {"QIANMIANLU_HOME": str(tmp_path / "home")}
    assert settings_path(env) == tmp_path / "home" / "config.json"
    s = load_settings(env=env)
    assert s == RatingSettings() and not s.configured
    assert s.missing() == ["base_url", "api_key", "model"]
    assert (s.max_retries, s.timeout, s.temperature) == (2, 300.0, 0.2)

    save_settings({"base_url": "https://x/v1", "api_key": KEY, "model": "m", "max_retries": 3}, env=env)
    s = load_settings(env=env)
    assert (s.base_url, s.api_key, s.model, s.max_retries) == ("https://x/v1", KEY, "m", 3)
    assert s.configured


def test_save_keeps_other_keys_and_keeps_key_when_none(tmp_path):
    env = {"QIANMIANLU_HOME": str(tmp_path)}
    path = settings_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"other": {"a": 1}, "rating": {"api_key": KEY, "model": "old"}}), encoding="utf-8")
    save_settings({"model": "new", "api_key": None}, env=env)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["other"] == {"a": 1}
    assert data["rating"] == {"api_key": KEY, "model": "new"}
    save_settings({"api_key": ""}, env=env)
    assert load_settings(env=env).api_key == ""


def test_env_overrides_file(tmp_path):
    env = {"QIANMIANLU_HOME": str(tmp_path)}
    save_settings({"base_url": "https://file/v1", "api_key": "file-key", "model": "file-model"}, env=env)
    env.update({
        ENV_PREFIX + "API_KEY": KEY, ENV_PREFIX + "MODEL": "env-model",
        ENV_PREFIX + "MAX_RETRIES": "5", ENV_PREFIX + "CONTEXT_CHAR_BUDGET": "12345",
        ENV_PREFIX + "TEMPERATURE": "0.7",
    })
    s = load_settings(env=env)
    assert (s.base_url, s.api_key, s.model) == ("https://file/v1", KEY, "env-model")
    assert (s.max_retries, s.context_char_budget, s.temperature) == (5, 12345, 0.7)


def test_settings_live_outside_project_and_library(tmp_path):
    p = user_data_dir({"LOCALAPPDATA": str(tmp_path / "local"), "XDG_CONFIG_HOME": str(tmp_path / "xdg")})
    assert p.name == "qianmianlu"
    assert "千面录" not in str(p) or str(tmp_path) in str(p)


def test_masked_view_and_repr_hide_key():
    s = RatingSettings(base_url="https://x", api_key=KEY, model="m")
    m = s.masked()
    assert KEY not in json.dumps(m) and m["api_key_set"] is True
    assert m["api_key"] == "sk-***cdef"
    assert KEY not in repr(s) and KEY not in str(s)
    assert mask_secret("") == "" and mask_secret("short") == "********"
    assert RatingSettings().masked()["api_key_set"] is False


def test_invalid_values_rejected_without_echoing_secret(tmp_path):
    env = {"QIANMIANLU_HOME": str(tmp_path), ENV_PREFIX + "TIMEOUT": "abc"}
    with pytest.raises(SettingsError):
        load_settings(env=env)
    with pytest.raises(SettingsError):
        save_settings({"max_retries": -1}, env={"QIANMIANLU_HOME": str(tmp_path)})
    with pytest.raises(SettingsError):
        save_settings({"nonsense": 1}, env={"QIANMIANLU_HOME": str(tmp_path)})
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "config.json").write_text("{not json " + KEY, encoding="utf-8")
    with pytest.raises(SettingsError) as ei:
        load_settings(env={"QIANMIANLU_HOME": str(bad)})
    assert KEY not in str(ei.value)
