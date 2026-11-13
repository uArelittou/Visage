import hashlib
import os

from backend.card import load_card, save_card


def detail(env, rel):
    r = env.client.get(f"/api/cards/{env.card_id(rel)}")
    assert r.status_code == 200, r.text
    return r.json()


def put(env, card_id, fields, **expect):
    return env.client.put(f"/api/cards/{card_id}", json={"fields": fields, **expect})


def external_edit(path, name="外部改的"):
    card = load_card(path)
    card.name = name
    save_card(path, card)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # 保证 mtime 与之前不同


# ------------------------------------------------------------------ 详情
def test_detail_has_all_sections(env):
    d = detail(env, "hero.png")
    c = d["card"]
    assert (d["path"], d["source"], d["sub"], d["file_name"], d["ext"]) == (
        env.path("hero.png"), env.root.as_posix(), "", "hero.png", ".png")
    assert c["name"] == "二号机" and c["description"] == "V2 描述" and c["personality"] == "冷静"
    assert c["scenario"] == "实验室" and c["creator"] == "tester" and c["tags"] == ["科幻", "机器人"]
    assert c["system_prompt"] == "你是二号机" and c["post_history_instructions"] == "保持角色"
    assert c["mes_example"] == "" and c["creator_notes"] == "作者备注"
    assert [g["text"] for g in c["greetings"]] == ["启动完毕。", "问候一", "问候二"]
    assert [g["index"] for g in c["greetings"]] == [0, 1, 2]
    assert c["alternate_greetings"] == ["问候一", "问候二"]
    assert len(c["character_book"]["entries"]) == 1
    assert c["character_book"]["entries"][0]["content"] == "词条内容"
    assert c["regex_scripts"][0]["scriptName"] == "去括号"
    assert c["scripts"][0]["name"] == "助手脚本"
    assert c["extensions"]["my_custom_plugin"]["flag"] is True


def test_detail_meta_matches_disk(env):
    d = detail(env, "hero.png")
    p = env.root / "hero.png"
    assert d["meta"]["hash"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert d["meta"]["mtime_ns"] == str(p.stat().st_mtime_ns)  # 字符串形式，不丢精度
    assert d["meta"]["size"] == p.stat().st_size and d["meta"]["is_broken"] is False


def test_detail_json_v3_and_broken(env):
    d = detail(env, "sub/second.json")
    assert d["card"]["name"] == "三号" and d["card"]["greetings"][0]["text"] == "v3 开场"
    assert d["card"]["scripts"][0]["name"] == "旧版脚本"
    bad = detail(env, "bad.png")
    assert bad["card"] is None and bad["meta"]["is_broken"] and bad["meta"]["error"]


def test_detail_unknown_id_and_deleted_file(env):
    assert env.client.get("/api/cards/99999").status_code == 404
    cid = env.card_id("hero.png")
    (env.root / "hero.png").unlink()
    r = env.client.get(f"/api/cards/{cid}")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "file_missing"


# ------------------------------------------------------------------ 保存
def tree_snapshot(*dirs):
    return {p: p.stat().st_mtime_ns for d in dirs for p in d.rglob("*") if p.is_file()}


def test_save_writes_source_file_in_place_without_backup(env):
    d = detail(env, "hero.png")
    before = tree_snapshot(env.root, env.config.parent)
    ext = d["card"]["extensions"]
    ext["regex_scripts"][0]["scriptName"] = "改过的正则"
    r = put(env, d["id"], {
        "name": "新名字", "tags": ["a", "b"], "alternate_greetings": ["只剩一个"],
        "extensions": ext,
    }, expected_mtime_ns=d["meta"]["mtime_ns"], expected_hash=d["meta"]["hash"])
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["id"] == d["id"] and new["card"]["name"] == "新名字"
    assert new["meta"]["hash"] != d["meta"]["hash"]
    assert new["card"]["regex_scripts"][0]["scriptName"] == "改过的正则"

    on_disk = load_card(env.root / "hero.png")
    assert on_disk.name == "新名字" and on_disk.tags == ["a", "b"]
    assert on_disk.alternate_greetings == ["只剩一个"]
    assert on_disk.description == "V2 描述"  # 没传的字段不动
    assert on_disk.raw["data"]["x_unknown_field"] == {"a": [1, {"b": None}], "c": "中文"}  # 未知字段保留

    after = tree_snapshot(env.root, env.config.parent)
    assert not [p for p in after if "backup" in p.as_posix().lower() or ".kabao" in p.as_posix()]
    assert {p for p in after if p.is_relative_to(env.root)} == {p for p in before if p.is_relative_to(env.root)}
    changed = [p for p in before if p.is_relative_to(env.root) and before[p] != after.get(p)]
    assert changed == [env.root / "hero.png"]  # 只有被编辑的源文件变了
    assert env.card("hero.png")["name"] == "新名字"  # 索引已刷新
    assert env.client.get("/api/cards", params={"q": "新名字"}).json()["total"] == 1


def test_save_with_stale_mtime_is_409_and_file_untouched(env):
    d = detail(env, "hero.png")
    external_edit(env.root / "hero.png")
    before = (env.root / "hero.png").read_bytes()
    r = put(env, d["id"], {"name": "不该写入"}, expected_mtime_ns=d["meta"]["mtime_ns"])
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "conflict" and body["reason"] == "modified"
    assert body["current"]["hash"] == hashlib.sha256(before).hexdigest()
    assert (env.root / "hero.png").read_bytes() == before
    assert not [p for p in env.root.rglob("*") if ".kabao" in p.as_posix()]


def test_save_with_stale_hash_only_is_409(env):
    d = detail(env, "hero.png")
    external_edit(env.root / "hero.png")
    r = put(env, d["id"], {"name": "不该写入"}, expected_hash=d["meta"]["hash"])
    assert r.status_code == 409 and load_card(env.root / "hero.png").name == "外部改的"


def test_save_after_reloading_detail_succeeds(env):
    d = detail(env, "hero.png")
    external_edit(env.root / "hero.png")
    fresh = detail(env, "hero.png")
    assert fresh["card"]["name"] == "外部改的"
    r = put(env, d["id"], {"description": "合并后"}, expected_mtime_ns=fresh["meta"]["mtime_ns"],
            expected_hash=fresh["meta"]["hash"])
    assert r.status_code == 200 and load_card(env.root / "hero.png").description == "合并后"


def test_touch_only_is_not_a_conflict_when_hash_given(env):
    d = detail(env, "hero.png")
    p = env.root / "hero.png"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
    r = put(env, d["id"], {"name": "仍可保存"}, expected_mtime_ns=d["meta"]["mtime_ns"],
            expected_hash=d["meta"]["hash"])
    assert r.status_code == 200


def test_expected_mtime_accepts_int_and_string(env):
    d = detail(env, "hero.png")
    r = put(env, d["id"], {"name": "A"}, expected_mtime_ns=int(d["meta"]["mtime_ns"]))
    assert r.status_code == 200
    d2 = r.json()
    r = put(env, d2["id"], {"name": "B"}, expected_mtime_ns=d2["meta"]["mtime_ns"])
    assert r.status_code == 200 and load_card(env.root / "hero.png").name == "B"


def test_save_requires_expectation_and_valid_fields(env):
    d = detail(env, "hero.png")
    exp = {"expected_hash": d["meta"]["hash"]}
    assert put(env, d["id"], {"name": "x"}).status_code == 400  # 没给 mtime/hash
    assert put(env, d["id"], {"name": "x"}, expected_mtime_ns="abc").status_code == 400
    assert put(env, d["id"], {"nope": 1}, **exp).status_code == 400
    assert put(env, d["id"], {"name": 123}, **exp).status_code == 400
    assert put(env, d["id"], {"tags": "a,b"}, **exp).status_code == 400
    assert put(env, d["id"], {"extensions": []}, **exp).status_code == 400
    assert put(env, d["id"], {"raw": {}}, **exp).status_code == 400
    assert put(env, 99999, {"name": "x"}, **exp).status_code == 404
    assert load_card(env.root / "hero.png").name == "二号机"


def test_save_json_card_in_place(env):
    d = detail(env, "sub/second.json")
    r = put(env, d["id"], {"name": "改名三号"}, expected_hash=d["meta"]["hash"])
    assert r.status_code == 200 and r.json()["path"] == env.path("sub/second.json")
    assert load_card(env.root / "sub" / "second.json").name == "改名三号"


def test_save_broken_card_is_422(env):
    d = detail(env, "bad.png")
    r = put(env, d["id"], {"name": "x"}, expected_hash=d["meta"]["hash"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "card_unreadable"


def test_save_webp_becomes_png_and_removes_webp(env):
    d = detail(env, "webcard.webp")
    cid = d["id"]
    env.client.put(f"/api/cards/{cid}/rating/user", json={"total": 7.5})
    r = put(env, cid, {"name": "网络图"}, expected_hash=d["meta"]["hash"])
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["path"] == env.path("webcard.png") and new["ext"] == ".png" and new["id"] != cid
    assert (env.root / "webcard.png").is_file() and not (env.root / "webcard.webp").exists()
    assert load_card(env.root / "webcard.png").name == "网络图"
    # 不做备份：原 WebP 按约定直接被 PNG 取代
    assert not [p for p in env.root.rglob("*") if ".kabao" in p.as_posix() or "backup" in p.name]
    paths = {i["path"] for i in env.client.get("/api/cards", params={"page_size": 500}).json()["items"]}
    assert env.path("webcard.png") in paths and env.path("webcard.webp") not in paths
    # 评分跟着搬到新文件
    assert env.client.get(f"/api/cards/{new['id']}/rating").json()["user_total"] == 7.5


def test_save_webp_refuses_to_overwrite_existing_png(env):
    (env.root / "webcard.png").write_bytes(env.mk.card_png(env.mk.V1_CARD, seed=2))
    env.client.post("/api/library/scan")
    d = detail(env, "webcard.webp")
    before = (env.root / "webcard.png").read_bytes()
    r = put(env, d["id"], {"name": "x"}, expected_hash=d["meta"]["hash"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "target_exists"
    assert (env.root / "webcard.webp").is_file() and (env.root / "webcard.png").read_bytes() == before


def test_save_pushes_change_event(env):
    v0 = env.client.get("/api/changes").json()["version"]
    d = detail(env, "hero.png")
    put(env, d["id"], {"name": "事件"}, expected_hash=d["meta"]["hash"])
    ch = env.client.get("/api/changes", params={"since": v0}).json()["changes"]
    assert any(c["kind"] == "saved" and c["path"] == env.path("hero.png") for c in ch)


def test_single_file_source_follows_webp_to_png(env, tmp_path):
    solo = tmp_path / "solo"
    solo.mkdir()
    (solo / "one.webp").write_bytes(env.mk.webp_card(env.mk.V3_CARD))
    r = env.client.post("/api/sources", json={"path": str(solo / "one.webp")})
    assert r.status_code == 201, r.text
    cid = env.client.get("/api/cards", params={"page_size": 500}).json()["items"]
    row = next(i for i in cid if i["path"] == (solo / "one.webp").as_posix())
    d = env.client.get(f"/api/cards/{row['id']}").json()
    r = put(env, row["id"], {"name": "单卡改名"}, expected_hash=d["meta"]["hash"])
    assert r.status_code == 200, r.text
    assert r.json()["path"] == (solo / "one.png").as_posix() and not (solo / "one.webp").exists()
    sources = [s["path"] for s in env.client.get("/api/sources").json()["sources"]]
    assert (solo / "one.png").as_posix() in sources and (solo / "one.webp").as_posix() not in sources
    assert env.client.post("/api/library/scan").status_code == 200
    names = [i["name"] for i in env.client.get("/api/cards", params={"page_size": 500}).json()["items"]]
    assert "单卡改名" in names

