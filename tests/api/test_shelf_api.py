import json
import shutil


def cats(env):
    return {i["key"]: i for i in env.client.get("/api/categories").json()["items"]}


def names(env, category=None, **params):
    if category:
        params["category"] = category
    r = env.client.get("/api/cards", params={"page_size": 500, **params})
    assert r.status_code == 200, r.text
    return sorted(i["name"] for i in r.json()["items"])


def new_collection(env, name):
    r = env.client.post("/api/collections", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ------------------------------------------------------------------ 分类
def test_home_categories_are_fixed_three_plus_user_ones(env):
    items = env.client.get("/api/categories").json()["items"]
    assert [(i["key"], i["name"], i["kind"]) for i in items] == [
        ("all", "全部", "all"), ("unsorted", "未分类", "unsorted"), ("favorites", "收藏", "favorites")]
    assert [i["count"] for i in items] == [5, 5, 0]  # 来源（文件夹）不出现在分类里
    cid = new_collection(env, "夜读")
    assert [i["name"] for i in env.client.get("/api/categories").json()["items"]][-1] == "夜读"
    assert cats(env)[f"c{cid}"]["count"] == 0


def test_collection_create_rename_delete_validation(env):
    a = new_collection(env, "甲")
    assert env.client.post("/api/collections", json={"name": "甲"}).status_code == 409
    assert env.client.post("/api/collections", json={"name": "  "}).status_code == 400
    assert env.client.post("/api/collections", json={"name": "长" * 40}).status_code == 400
    b = new_collection(env, "乙")
    assert env.client.patch(f"/api/collections/{b}", json={"name": "甲"}).json()["detail"]["code"] == "name_exists"
    assert env.client.patch(f"/api/collections/{b}", json={"name": " 丙  丁 "}).json() == {"id": b, "name": "丙 丁"}
    assert env.client.patch("/api/collections/999", json={"name": "x"}).status_code == 404
    assert env.client.delete(f"/api/collections/{a}").status_code == 200
    assert env.client.delete(f"/api/collections/{a}").status_code == 404
    assert [i["name"] for i in env.client.get("/api/categories").json()["items"]][3:] == ["丙 丁"]


def test_put_card_into_and_out_of_collections(env):
    x, y = new_collection(env, "X"), new_collection(env, "Y")
    hero = env.card_id("hero.png")
    r = env.client.put(f"/api/cards/{hero}/collections", json={"ids": [x, y]})
    assert r.status_code == 200 and r.json() == {"favorite": False, "collections": [x, y]}
    assert names(env, f"c{x}") == ["二号机"] and names(env, f"c{y}") == ["二号机"]
    row = env.card("hero.png")
    assert row["collections"] == [x, y] and row["favorite"] is False
    c = cats(env)
    assert (c["all"]["count"], c["unsorted"]["count"], c[f"c{x}"]["count"]) == (5, 4, 1)
    unsorted = {i["path"] for i in env.client.get("/api/cards", params={"category": "unsorted"}).json()["items"]}
    assert env.path("hero.png") not in unsorted and env.path("webcard.webp") in unsorted

    env.client.put(f"/api/cards/{hero}/collections", json={"ids": [y]})
    assert names(env, f"c{x}") == [] and names(env, f"c{y}") == ["二号机"]
    env.client.put(f"/api/cards/{hero}/collections", json={"ids": []})
    assert cats(env)["unsorted"]["count"] == 5
    assert env.client.put("/api/cards/99999/collections", json={"ids": []}).status_code == 404
    assert env.client.get("/api/cards", params={"category": "c999"}).json()["total"] == 0


def test_deleting_collection_keeps_cards_and_files(env):
    x = new_collection(env, "X")
    hero = env.card_id("hero.png")
    env.client.put(f"/api/cards/{hero}/collections", json={"ids": [x]})
    assert env.client.delete(f"/api/collections/{x}").status_code == 200
    assert (env.root / "hero.png").is_file() and len(names(env)) == 5
    assert cats(env)["unsorted"]["count"] == 5
    assert env.card("hero.png")["collections"] == []


def test_favorite_toggle_and_view(env):
    hero = env.card_id("hero.png")
    r = env.client.put(f"/api/cards/{hero}/favorite", json={"value": True})
    assert r.status_code == 200 and r.json()["favorite"] is True
    assert names(env, "favorites") == ["二号机"] and cats(env)["favorites"]["count"] == 1
    assert env.card("hero.png")["favorite"] is True
    assert env.client.get("/api/cards", params={"category": "favorites", "q": "二号机"}).json()["total"] == 1
    env.client.put(f"/api/cards/{hero}/favorite", json={"value": False})
    assert names(env, "favorites") == []


def test_shelf_data_is_not_written_into_card_files(env):
    before = (env.root / "hero.png").read_bytes()
    x = new_collection(env, "X")
    hero = env.card_id("hero.png")
    env.client.put(f"/api/cards/{hero}/collections", json={"ids": [x]})
    env.client.put(f"/api/cards/{hero}/favorite", json={"value": True})
    assert (env.root / "hero.png").read_bytes() == before
    assert (env.config.parent / "library.db").is_file()


def test_shelf_survives_clear_and_rescan_with_ratings(env):
    x = new_collection(env, "X")
    hero = env.card_id("hero.png")
    env.client.put(f"/api/cards/{hero}/collections", json={"ids": [x]})
    env.client.put(f"/api/cards/{hero}/favorite", json={"value": True})
    env.client.put(f"/api/cards/{hero}/rating/user", json={"total": 7.5})

    r = env.client.post("/api/library/clear")
    assert r.status_code == 200 and r.json()["cleared"] == 5
    assert names(env) == [] and cats(env)["all"]["count"] == 0
    assert f"c{x}" in cats(env)  # 分类本身还在
    assert env.client.get("/api/library").json()["card_count"] == 0

    assert env.client.post("/api/library/scan").status_code == 200
    assert names(env, "favorites") == ["二号机"] and names(env, f"c{x}") == ["二号机"]
    new_id = env.card_id("hero.png")
    assert env.client.get(f"/api/cards/{new_id}/rating").json()["user_total"] == 7.5


# ------------------------------------------------------------------ 来源（只在设置页管理）
def test_sources_dedupe_merge_and_remove_over_api(env, tmp_path):
    inner = env.root / "sub"
    r = env.client.post("/api/sources", json={"path": str(inner)})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "already_in_library" and d["message"] == "已在卡库里" and d["source"] == env.root.as_posix()
    assert env.client.post("/api/sources", json={"path": str(env.root / "hero.png")}).status_code == 409

    solo_dir = tmp_path / "loose"
    solo_dir.mkdir()
    solo = solo_dir / "solo.json"
    solo.write_text(json.dumps(env.mk.V1_CARD, ensure_ascii=False), encoding="utf-8")
    r = env.client.post("/api/sources", json={"path": str(solo)})
    assert r.status_code == 201 and r.json()["source"]["kind"] == "file" and r.json()["card_count"] == 6
    assert len(names(env)) == 6

    # 加入包含已有来源的父文件夹：子来源并入
    r = env.client.post("/api/sources", json={"path": str(tmp_path)})
    assert r.status_code == 201, r.text
    assert sorted(r.json()["merged"]) == sorted([env.root.as_posix(), solo.as_posix()])
    srcs = env.client.get("/api/sources").json()["sources"]
    assert [s["path"] for s in srcs] == [tmp_path.as_posix()]

    # 移除来源只删索引，不删文件
    r = env.client.delete("/api/sources", params={"path": str(tmp_path)})
    assert r.status_code == 200 and r.json()["card_count"] == 0
    assert (env.root / "hero.png").is_file() and solo.is_file()
    assert env.client.delete("/api/sources", params={"path": str(tmp_path)}).status_code == 404


def test_same_content_in_two_sources_listed_once(env, tmp_path):
    twin_dir = tmp_path / "twin"
    twin_dir.mkdir()
    shutil.copy(env.root / "hero.png", twin_dir / "hero_copy.png")
    assert env.client.post("/api/sources", json={"path": str(twin_dir)}).status_code == 201
    assert len(names(env)) == 5 and cats(env)["all"]["count"] == 5
    assert env.client.get("/api/library").json()["card_count"] == 5


def test_dot_folders_are_not_indexed(env, tmp_path):
    other = tmp_path / "other"
    (other / ".bak_history").mkdir(parents=True)
    shutil.copy(env.root / "hero.png", other / ".bak_history" / "old.png")
    (other / "keep.json").write_text(json.dumps(env.mk.V1_CARD, ensure_ascii=False), encoding="utf-8")
    r = env.client.post("/api/sources", json={"path": str(other)})
    assert r.status_code == 201 and r.json()["scan"]["added"] == 1
    paths = [i["path"] for i in env.client.get("/api/cards", params={"page_size": 500}).json()["items"]]
    assert not any(".bak_history" in p for p in paths)
