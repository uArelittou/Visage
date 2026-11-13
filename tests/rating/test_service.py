import json
import os
import re
import shutil
import traceback
import urllib.request
from pathlib import Path

import pytest
from rating_helpers import FakeServer, ok_body

from backend.card import load_card
from backend.library import Library
from backend.rating.blocks import card_blocks
from backend.rating.llm import ChatResult, LLMError, OpenAIChatClient
from backend.rating.service import (
    CardNotFoundError, RatingBusyError, RatingConfigError, RatingError, RatingFailed, RatingService,
)
from backend.rating.settings import RatingSettings

KEY = "sk-SERVICE-SECRET-0123456789abcdef"


def settings(**kw) -> RatingSettings:
    base = dict(base_url="http://127.0.0.1:1/v1", api_key=KEY, model="fake-model",
                max_retries=2, context_char_budget=200_000)
    base.update(kw)
    return RatingSettings(**base)


class FakeClient:
    model = "fake-model"

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[list[dict]] = []

    def complete(self, messages):
        self.calls.append(messages)
        out = self.handler(messages, len(self.calls))
        if isinstance(out, ChatResult):
            return out
        return ChatResult(text=out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
                          finish_reason="stop", model=self.model)


def user_text(messages) -> str:
    return messages[1]["content"]


def segment_reply(sample, user: str) -> dict:
    index, total = map(int, re.search(r"第 (\d+) 段，共 (\d+) 段", user).groups())
    locs = re.search(r"【本段区块清单】\n([\s\S]*?)\n\n【本段卡内容】", user).group(1).split("\n")

    def quote(loc):
        line = max(sample.texts[loc].splitlines()[:5], key=lambda x: len(x.strip())).strip()
        return {"quote": line[:50], "location": loc}

    greetings = []
    for loc in locs:
        if loc.startswith("开场白#"):
            q = quote(loc)
            greetings.append({
                "index": int(loc.split("#")[1]), "guidance": 3, "guidance_evidence": [q],
                "freedom": 2, "freedom_evidence": [q], "reason": "ok",
            })
    return {
        "mode": "segment", "segment_index": index, "segment_total": total, "locations_read": locs,
        "notes": [{"dimension": "character", "polarity": "neutral", "note": "n", "evidence": [quote(locs[0])]}],
        "facts": [], "greetings": greetings, "deduction_candidates": [], "na_hints": [],
        "injection_notes": [],
    }


@pytest.fixture
def env(tmp_path, lin):
    root = tmp_path / "cards"
    root.mkdir()
    shutil.copy(lin.path, root / "lin.json")
    lib = Library(tmp_path / "data", load_card, debounce=0.1)
    lib.open([root])
    yield lib, lib.get_card_by_path(croot(lib) / "lin.json")["id"]
    lib.close()


def croot(lib):
    return Path(lib.sources[0].path)


def service(lib, client=None, **kw) -> RatingService:
    s = kw.pop("settings", settings())
    return RatingService(lib, settings_provider=lambda: s, client=client, **kw)


def good(lin):
    return lambda messages, n: lin.output


def bump_mtime(path, seconds=5):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 1_000_000_000))


# ------------------------------------------------------------------ 整卡
def test_rate_card_full_mode(env, lin):
    lib, cid = env
    client = FakeClient(good(lin))
    r = service(lib, client).rate_card(cid)
    assert len(client.calls) == 1
    assert client.calls[0][0]["role"] == "system" and "整卡模式" in user_text(client.calls[0])
    assert r["ai_total"] == 8.0 and r["display_score"] == 8.0 and r["user_total"] is None
    assert (r["model"], r["rubric_version"], r["has_ai"]) == ("fake-model", 2, True)
    assert r["rated_at"] and r["result"]["meta"] == {"mode": "full", "segments": 1}
    dims = r["result"]["dimensions"]
    assert dims["character"]["score"] == 9 and dims["character"]["evidence"] and dims["character"]["reason"]
    assert r["result"]["opening"]["count_score"] == 3
    assert r["result"]["bonus"]["items"]["style"]["score"] == 0.1
    assert r["result"]["deductions"]["items"][0]["quotes"]
    assert r["result"]["review"] == lin.output["review"]
    assert service(lib, client).get_rating(cid) == r


def test_unrated_card_has_empty_rating(env):
    lib, cid = env
    r = service(lib, FakeClient(lambda m, n: "")).get_rating(cid)
    assert r["display_score"] is None and not r["has_ai"] and r["result"] is None


# ------------------------------------------------------------------ 重试
def test_invalid_replies_are_fed_back_then_succeed(env, lin):
    lib, cid = env
    fake_quote = lin.output
    fake_quote["deductions"][0]["quotes"] = [{"quote": "这句话卡里根本没有出现过呢", "location": "开场白#0"}]
    replies = ["我无法评分", fake_quote, lin.output]
    client = FakeClient(lambda m, n: replies[n - 1])
    r = service(lib, client).rate_card(cid)
    assert len(client.calls) == 3 and r["ai_total"] == 8.0
    second, third = client.calls[1], client.calls[2]
    assert second[-1]["role"] == "user" and "不是合法 JSON" in second[-1]["content"]
    assert second[-2] == {"role": "assistant", "content": "我无法评分"}
    assert "deductions[0].quotes[0]" in third[-1]["content"] and "找不到" in third[-1]["content"]


def test_gives_up_after_configured_retries_and_stores_nothing(env, lin):
    lib, cid = env
    client = FakeClient(lambda m, n: "不是 JSON")
    svc = service(lib, client, settings=settings(max_retries=1))
    with pytest.raises(RatingFailed) as ei:
        svc.rate_card(cid)
    assert len(client.calls) == 2 and ei.value.errors
    r = svc.get_rating(cid)
    assert not r["has_ai"] and r["ai_total"] is None
    assert lib.db.get_rating_row((croot(lib) / "lin.json").as_posix()) is None
    zero = FakeClient(lambda m, n: "x")
    with pytest.raises(RatingFailed):
        service(lib, zero, settings=settings(max_retries=0)).rate_card(cid)
    assert len(zero.calls) == 1


def test_failed_rerate_keeps_previous_result(env, lin):
    lib, cid = env
    service(lib, FakeClient(good(lin))).rate_card(cid)
    with pytest.raises(RatingFailed):
        service(lib, FakeClient(lambda m, n: "坏")).rate_card(cid)
    assert service(lib, FakeClient(good(lin))).get_rating(cid)["ai_total"] == 8.0


def test_truncated_reply_is_retried(env, lin):
    lib, cid = env

    def handler(messages, n):
        if n == 1:
            return ChatResult(text='{"mode": "final", "card', finish_reason="length")
        return lin.output

    client = FakeClient(handler)
    assert service(lib, client).rate_card(cid)["ai_total"] == 8.0
    assert "截断" in client.calls[1][-1]["content"]
    assert all(m["content"] != '{"mode": "final", "card' for m in client.calls[1])


def test_fenced_json_is_accepted(env, lin):
    lib, cid = env
    client = FakeClient(lambda m, n: "```json\n" + json.dumps(lin.output, ensure_ascii=False) + "\n```")
    assert service(lib, client).rate_card(cid)["ai_total"] == 8.0
    assert len(client.calls) == 1


# ------------------------------------------------------------------ 分段合并
def test_segmented_flow_merges_and_scores(env, lin):
    lib, cid = env

    def handler(messages, n):
        user = user_text(messages)
        if "分段模式，第" in user:
            return segment_reply(lin, user)
        assert "合并模式" in user
        return lin.output

    client = FakeClient(handler)
    r = service(lib, client, settings=settings(context_char_budget=30_000)).rate_card(cid)
    meta = r["result"]["meta"]
    assert meta["mode"] == "segmented" and meta["segments"] >= 2
    assert len(client.calls) == meta["segments"] + 1
    users = [user_text(c) for c in client.calls]
    for i, u in enumerate(users[:-1], 1):
        assert f"第 {i} 段，共 {meta['segments']} 段" in u
        assert len(client.calls[i - 1][0]["content"]) + len(u) <= 30_000
    assert "合并模式" in users[-1] and "CARD_BEGIN" in users[-1]
    # 合并消息里带的是各段结果，不是整张卡
    assert users[-1].count('"mode": "segment"') == meta["segments"]
    read = set()
    for u in users[:-1]:
        read |= set(re.search(r"【本段区块清单】\n([\s\S]*?)\n\n", u).group(1).split("\n"))
    assert read == {b.location for b in card_blocks(lin.card)}
    assert r["ai_total"] == 8.0


def test_context_overflow_falls_back_to_segments(env, lin):
    lib, cid = env

    def handler(messages, n):
        user = user_text(messages)
        if "整卡模式" in user:
            raise LLMError("HTTP 400: This model's maximum context length is 8192 tokens", status=400)
        if "分段模式，第" in user:
            return segment_reply(lin, user)
        return lin.output

    client = FakeClient(handler)
    r = service(lib, client).rate_card(cid)
    meta = r["result"]["meta"]
    assert meta["mode"] == "segmented" and meta["segments"] >= 2
    assert "整卡模式" in user_text(client.calls[0])
    assert r["ai_total"] == 8.0


def test_other_llm_errors_do_not_fall_back(env, lin):
    lib, cid = env

    def handler(messages, n):
        raise LLMError("HTTP 401: invalid api key", status=401)

    client = FakeClient(handler)
    with pytest.raises(LLMError):
        service(lib, client).rate_card(cid)
    assert len(client.calls) == 1


def test_default_budget_sends_big_card_in_one_request(tmp_path, mofa):
    root = tmp_path / "cards"
    root.mkdir()
    shutil.copy(mofa.path, root / "mofa.json")
    lib = Library(tmp_path / "data", load_card, debounce=0.1)
    lib.open([root])
    try:
        cid = lib.get_card_by_path(croot(lib) / "mofa.json")["id"]
        client = FakeClient(lambda m, n: mofa.output)
        r = service(lib, client, settings=RatingSettings(
            base_url="http://127.0.0.1:1/v1", api_key=KEY, model="fake-model")).rate_card(cid)
        assert len(client.calls) == 1 and r["result"]["meta"]["mode"] == "full"
    finally:
        lib.close()


def test_segment_output_with_wrong_index_is_retried(env, lin):
    lib, cid = env
    state = {"bad": True}

    def handler(messages, n):
        user = user_text(messages)
        if "分段模式，第" in user:
            out = segment_reply(lin, user)
            if state["bad"]:
                state["bad"] = False
                out["segment_index"] = 99
            return out
        return lin.output

    client = FakeClient(handler)
    r = service(lib, client, settings=settings(context_char_budget=30_000)).rate_card(cid)
    assert len(client.calls) == r["result"]["meta"]["segments"] + 2
    assert "segment_index" in client.calls[1][-1]["content"]


def test_budget_too_small_for_segments(env, lin):
    lib, cid = env
    with pytest.raises(RatingConfigError, match="预算"):
        service(lib, FakeClient(good(lin)), settings=settings(context_char_budget=9_000)).rate_card(cid)


# ------------------------------------------------------------------ 用户总分
def test_user_total_survives_rerate_and_can_be_cleared(env, lin):
    lib, cid = env
    svc = service(lib, FakeClient(good(lin)))
    r = svc.set_user_total(cid, 7.25)
    assert r["user_total"] == 7.3 and r["display_score"] == 7.3 and not r["has_ai"]
    r = svc.rate_card(cid)
    assert (r["user_total"], r["ai_total"], r["display_score"]) == (7.3, 8.0, 7.3)
    r = svc.rate_card(cid)
    assert r["user_total"] == 7.3 and r["display_score"] == 7.3
    r = svc.set_user_total(cid, 9)
    assert r["display_score"] == 9 and r["ai_total"] == 8.0
    r = svc.clear_user_total(cid)
    assert r["user_total"] is None and r["display_score"] == 8.0 and r["user_rated_at"] is None


def test_clear_user_total_without_ai_leaves_no_row(env):
    lib, cid = env
    svc = service(lib, FakeClient(lambda m, n: ""))
    svc.set_user_total(cid, 5)
    r = svc.clear_user_total(cid)
    assert r["display_score"] is None
    assert lib.db.get_rating_row((croot(lib) / "lin.json").as_posix()) is None
    svc.clear_user_total(cid)  # 重复清除不报错


@pytest.mark.parametrize("bad", [-0.1, 10.1, float("nan"), True, "9", None])
def test_user_total_validation(env, bad):
    lib, cid = env
    with pytest.raises(ValueError):
        service(lib, FakeClient(lambda m, n: "")).set_user_total(cid, bad)


def test_unknown_and_broken_cards(env, tmp_path, lin):
    lib, cid = env
    svc = service(lib, FakeClient(good(lin)))
    for call in (svc.get_rating, svc.rate_card, svc.clear_user_total):
        with pytest.raises(CardNotFoundError):
            call(9999)
    (croot(lib) / "bad.json").write_text("{not a card", encoding="utf-8")
    lib.scan()
    bad_id = lib.get_card_by_path(croot(lib) / "bad.json")["id"]
    with pytest.raises(RatingError, match="无法解析"):
        svc.rate_card(bad_id)


def test_concurrent_rating_of_same_card_is_rejected(env, lin):
    lib, cid = env
    holder = {}

    def handler(messages, n):
        with pytest.raises(RatingBusyError):
            holder["svc"].rate_card(cid)
        return lin.output

    svc = service(lib, FakeClient(handler))
    holder["svc"] = svc
    assert svc.rate_card(cid)["ai_total"] == 8.0
    assert svc.rate_card(cid)["ai_total"] == 8.0  # 结束后可再评


def test_missing_config_names_fields_only(env):
    lib, cid = env
    svc = RatingService(lib, settings_provider=lambda: RatingSettings(api_key=KEY))
    with pytest.raises(RatingConfigError) as ei:
        svc.rate_card(cid)
    assert "base_url" in str(ei.value) and "model" in str(ei.value) and KEY not in str(ei.value)


# ------------------------------------------------------------------ 改内容 / 改名
def test_rating_stays_after_card_is_edited(env, lin):
    lib, cid = env
    svc = service(lib, FakeClient(good(lin)))
    svc.rate_card(cid)
    svc.set_user_total(cid, 6)
    p = croot(lib) / "lin.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["data"]["name"] = "改过名字的卡"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    bump_mtime(p)
    old_hash = lib.get_card(cid)["hash"]
    lib.scan()
    row = lib.get_card_by_path(croot(lib) / "lin.json")
    assert row["id"] == cid and row["hash"] != old_hash
    r = svc.get_rating(cid)
    assert (r["ai_total"], r["user_total"], r["display_score"]) == (8.0, 6, 6)
    assert "stale" not in json.dumps(r) and "过期" not in json.dumps(r, ensure_ascii=False)
    assert lib.db.get_rating_row((croot(lib) / "lin.json").as_posix())["content_hash"] == row["hash"]


def test_rating_follows_renamed_and_moved_card(env, lin):
    lib, cid = env
    svc = service(lib, FakeClient(good(lin)))
    svc.rate_card(cid)
    svc.set_user_total(cid, 6.5)
    (croot(lib) / "sub").mkdir()
    (croot(lib) / "lin.json").rename(croot(lib) / "sub" / "新名字.json")
    lib.scan()
    assert lib.get_card_by_path(croot(lib) / "lin.json") is None
    new_id = lib.get_card_by_path(croot(lib) / "sub/新名字.json")["id"]
    assert new_id != cid  # 改名后 cards 行是新的，评分靠哈希接回
    r = svc.get_rating(new_id)
    assert (r["ai_total"], r["user_total"], r["display_score"]) == (8.0, 6.5, 6.5)
    assert r["result"]["dimensions"]["character"]["score"] == 9
    assert lib.db.get_rating_row((croot(lib) / "lin.json").as_posix()) is None


def test_edit_then_rename_still_finds_rating(env, lin):
    lib, cid = env
    svc = service(lib, FakeClient(good(lin)))
    svc.rate_card(cid)
    p = croot(lib) / "lin.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["data"]["name"] = "先改内容"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    bump_mtime(p)
    lib.scan()
    p.rename(croot(lib) / "renamed.json")
    lib.scan()
    assert svc.get_rating(lib.get_card_by_path(croot(lib) / "renamed.json")["id"])["ai_total"] == 8.0


def test_rename_does_not_steal_rating_from_another_card(env, lin):
    lib, cid = env
    svc = service(lib, FakeClient(good(lin)))
    svc.rate_card(cid)
    shutil.copy(croot(lib) / "lin.json", croot(lib) / "copy.json")
    lib.scan()
    copy_id = lib.get_card_by_path(croot(lib) / "copy.json")["id"]
    assert not svc.get_rating(copy_id)["has_ai"]  # 原卡还在，副本不会继承评分
    assert svc.get_rating(cid)["has_ai"]


def test_old_relative_path_database_is_upgraded(tmp_path):
    """v2 索引按相对路径建，和现在的绝对路径不兼容：索引丢弃重建，旧评分改挂路径列并等待按 hash 接回。"""
    import sqlite3

    from backend.library.db import CardRecord, Database

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE cards (id INTEGER PRIMARY KEY AUTOINCREMENT, rel_path TEXT NOT NULL UNIQUE,"
        " folder TEXT NOT NULL DEFAULT '', file_name TEXT NOT NULL, ext TEXT NOT NULL,"
        " name TEXT NOT NULL DEFAULT '', mtime_ns INTEGER NOT NULL,"
        " size INTEGER NOT NULL, hash TEXT NOT NULL, scanned_at REAL NOT NULL);"
        "CREATE TABLE card_ratings (rel_path TEXT PRIMARY KEY, content_hash TEXT NOT NULL, ai_total REAL,"
        " ai_result TEXT, model TEXT NOT NULL DEFAULT '', rubric_version INTEGER, rated_at REAL,"
        " user_total REAL, user_rated_at REAL);"
        "INSERT INTO cards(rel_path,file_name,ext,mtime_ns,size,hash,scanned_at) VALUES ('a.json','a.json','.json',1,1,'h',0);"
        "INSERT INTO card_ratings(rel_path, content_hash, user_total) VALUES ('a.json', 'h', 4.5);"
    )
    con.commit()
    con.close()
    db = Database(path)
    assert db.count() == 0  # 旧索引已丢弃
    db.upsert(CardRecord(path="D:/cards/a.json", source="D:/cards", mtime_ns=1, size=1, hash="h"))
    assert db.relink_ratings() == 1
    assert db.get_rating_row("D:/cards/a.json")["user_total"] == 4.5
    db.close()


# ------------------------------------------------------------------ 密钥
def test_key_never_in_exception_or_traceback_on_http_failure(env):
    lib, cid = env
    echo = lambda headers, body: json.dumps({"error": f"invalid {headers['Authorization']}"}).encode()  # noqa: E731
    with FakeServer([(401, echo)]) as srv:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

        def factory(s):
            return OpenAIChatClient(srv.url, s.api_key, s.model, opener=opener)

        svc = RatingService(lib, settings_provider=lambda: settings(base_url=srv.url),
                            client_factory=factory)
        with pytest.raises(LLMError) as ei:
            svc.rate_card(cid)
    tb = "".join(traceback.format_exception(ei.value))
    assert KEY not in tb and KEY not in str(ei.value) and KEY not in repr(ei.value)
    assert lib.db.get_rating_row((croot(lib) / "lin.json").as_posix()) is None


def test_key_never_in_database_or_result(env, lin, tmp_path):
    lib, cid = env
    with FakeServer([(200, ok_body(json.dumps(lin.output, ensure_ascii=False)))]) as srv:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

        def factory(s):
            return OpenAIChatClient(srv.url, s.api_key, s.model, opener=opener)

        svc = RatingService(lib, settings_provider=lambda: settings(base_url=srv.url),
                            client_factory=factory)
        r = svc.rate_card(cid)
    assert srv.requests[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert r["ai_total"] == 8.0 and r["model"] == "fake-model"
    assert KEY not in json.dumps(r, ensure_ascii=False)
    svc.set_user_total(cid, 7)
    db_path = lib.db.path
    lib.db.close()
    blob = b"".join(p.read_bytes() for p in db_path.parent.glob(db_path.name + "*"))
    assert blob and KEY.encode() not in blob
    lib.db = None
