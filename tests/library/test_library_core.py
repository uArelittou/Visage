import io
import os
import threading
import time

import pytest
from PIL import Image

from backend.library import AlreadyInLibrary, BackupManager, ConflictError, Library, SourceError
from library_helpers import write_card


def png_bytes(w=800, h=1200, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def key(root, rel):
    return (root / rel).as_posix()


def bump(p, ns=5_000_000_000):
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + ns))


# ---------- 扫描 ----------
def test_incremental_scan_skips_unchanged(lib, loader, root):
    write_card(root, "a.json", name="Alice")
    write_card(root, "sub/b.json", name="Bob")
    r1 = lib.open([root])
    assert (r1.added, r1.skipped) == (2, 0)
    assert sorted(loader.calls) == ["a.json", "b.json"]
    loader.calls.clear()

    r2 = lib.scan()
    assert (r2.added, r2.updated, r2.skipped) == (0, 0, 2)
    assert loader.calls == []

    p = write_card(root, "a.json", name="Alice2")
    bump(p)
    r3 = lib.scan()
    assert (r3.updated, r3.skipped) == (1, 1)
    assert loader.calls == ["a.json"]
    assert lib.get_card_by_path(key(root, "a.json"))["name"] == "Alice2"


def test_touch_without_content_change_does_not_reparse(lib, loader, root):
    p = write_card(root, "a.json", name="Alice")
    lib.open([root])
    loader.calls.clear()
    st = p.stat()
    bump(p)
    r = lib.scan()
    assert loader.calls == [] and r.skipped == 1 and r.updated == 0
    assert lib.get_card_by_path(p)["mtime_ns"] == st.st_mtime_ns + 5_000_000_000


def test_subfolders_stay_inside_source_and_keep_sub_path(lib, root):
    write_card(root, "top.json", name="Top")
    write_card(root, "A/a1.json", name="A1")
    write_card(root, "A/B/ab1.json", name="AB1")
    (root / "empty").mkdir()
    lib.open([root])
    assert lib.list_cards().total == 3
    deep = lib.get_card_by_path(key(root, "A/B/ab1.json"))
    assert deep["source"] == root.as_posix() and deep["sub"] == "A/B"
    assert lib.get_card_by_path(key(root, "top.json"))["sub"] == ""


def test_dot_folders_are_skipped(lib, root):
    write_card(root, "a.json", name="A")
    write_card(root, ".bak_history/old.json", name="Old")
    write_card(root, "sub/.hidden/x.json", name="Hidden")
    write_card(root, "a.json.tmp", name="Tmp")
    lib.open([root])
    assert [c["name"] for c in lib.list_cards().items] == ["A"]


def test_data_dir_inside_source_is_not_indexed(tmp_path, loader):
    root = tmp_path / "cards"
    write_card(root, "a.json", name="A")
    data = root / "qml-data"  # 用户把数据目录放进了卡文件夹
    with Library(data, loader) as lib:
        lib.open([root])
        (data / "thumbs").mkdir(exist_ok=True)
        write_card(data, "config.json", name="NotACard")
        (data / "thumbs" / "x.webp").write_bytes(b"x")
        lib.scan()
        assert [c["name"] for c in lib.list_cards().items] == ["A"]


def test_broken_card_does_not_abort_scan(lib, root):
    write_card(root, "good1.json", name="Good1")
    (root / "bad.json").write_text("BROKEN", encoding="utf-8")
    write_card(root, "good2.json", name="Good2")
    r = lib.open([root])
    assert r.added == 3 and r.broken == 1
    bad = lib.get_card_by_path(key(root, "bad.json"))
    assert bad["is_broken"] and "not a card" in bad["error"]
    assert not lib.get_card_by_path(key(root, "good1.json"))["is_broken"]
    assert lib.get_thumbnail(bad["id"]) is None


def test_card_fields_extracted(lib, root):
    write_card(
        root, "x.json", name="魔法少女", creator="作者甲", tags=["奇幻", "日常"],
        description="一个会魔法的女孩", first_mes="你好", alternate_greetings=["嗨", "哟"],
        character_book={"entries": [{}, {}, {}]}, regex_scripts=[{}], scripts=[{}, {}],
    )
    lib.open([root])
    c = lib.get_card_by_path(key(root, "x.json"))
    assert (c["greeting_count"], c["lorebook_count"], c["regex_count"], c["script_count"]) == (3, 3, 1, 2)
    assert c["tags"] == ["奇幻", "日常"] and c["creator"] == "作者甲"
    assert lib.get_card(c["id"])["path"] == key(root, "x.json")


# ---------- 多来源、去重 ----------
def test_multiple_sources_index_in_place(lib, tmp_path, root):
    other = tmp_path / "other"
    write_card(root, "a.json", name="A")
    write_card(other, "b.json", name="B")
    solo = write_card(tmp_path / "loose", "c.json", name="C")
    lib.open([root])
    r1 = lib.add_source(other)
    r2 = lib.add_source(solo)
    assert (r1.scan.added, r2.scan.added) == (1, 1)
    assert sorted(c["name"] for c in lib.list_cards().items) == ["A", "B", "C"]
    kinds = {s["path"]: s["kind"] for s in lib.list_sources()}
    assert kinds == {root.as_posix(): "folder", other.as_posix(): "folder", solo.as_posix(): "file"}
    # 原地索引：没有复制任何文件
    assert sorted(p.name for p in tmp_path.rglob("*.json") if "data" not in p.parts) == ["a.json", "b.json", "c.json"]
    assert lib.get_card_by_path(solo)["sub"] == ""


def test_adding_same_or_covered_path_is_rejected(lib, tmp_path, root):
    inner = write_card(root, "sub/x.json", name="X")
    lib.open([root])
    for dup in (root, root / "sub", inner):
        with pytest.raises(AlreadyInLibrary):
            lib.add_source(dup)
    assert len(lib.sources) == 1
    with pytest.raises(AlreadyInLibrary):
        lib.add_source(str(root).upper() if os.name == "nt" else root)
    with pytest.raises(SourceError) as ei:
        lib.add_source(tmp_path / "nope")
    assert ei.value.code == "path_not_found"
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(SourceError) as ei:
        lib.add_source(txt)
    assert ei.value.code == "bad_ext"
    bad = tmp_path / "bad.json"
    bad.write_text("BROKEN", encoding="utf-8")
    with pytest.raises(SourceError) as ei:
        lib.add_source(bad)
    assert ei.value.code == "not_a_card"


def test_path_inside_dot_folder_is_not_covered(lib, root):
    write_card(root, "a.json", name="A")
    write_card(root, ".bak_history/old.json", name="Old")
    lib.open([root])
    lib.add_source(root / ".bak_history")  # 父文件夹不扫它，所以不算「已在卡库里」
    assert sorted(c["name"] for c in lib.list_cards().items) == ["A", "Old"]


def test_adding_parent_folder_merges_child_sources(lib, tmp_path):
    parent = tmp_path / "parent"
    write_card(parent, "p.json", name="P")
    k1 = write_card(parent, "kids/k1.json", name="K1")
    write_card(parent, "kids2/k2.json", name="K2")
    solo = write_card(parent, "kids2/solo.json", name="Solo")
    lib.open([k1.parent])
    lib.add_source(solo)
    assert len(lib.sources) == 2
    ids_before = {c["path"]: c["id"] for c in lib.list_cards().items}
    assert len(ids_before) == 2

    res = lib.add_source(parent)
    assert {s.path for s in res.merged} == {k1.parent.as_posix(), solo.as_posix()}
    assert [s.path for s in lib.sources] == [parent.as_posix()]
    items = lib.list_cards().items
    assert sorted(c["name"] for c in items) == ["K1", "K2", "P", "Solo"]
    assert all(c["source"] == parent.as_posix() for c in items)
    # 重叠的卡只是改挂到父文件夹名下，行没有被删了重建
    assert {c["path"]: c["id"] for c in items if c["path"] in ids_before} == ids_before


def test_remove_source_only_drops_index(lib, tmp_path, root):
    other = tmp_path / "other"
    a = write_card(root, "a.json", name="A")
    b = write_card(other, "b.json", name="B")
    lib.open([root, other])
    lib.db.set_user_total(a.as_posix(), lib.get_card_by_path(a)["hash"], 7.5)
    assert lib.remove_source(root).path == root.as_posix()
    assert [c["name"] for c in lib.list_cards().items] == ["B"]
    assert a.exists() and b.exists()  # 文件一个不动
    assert lib.remove_source(root) is None
    assert lib.db.get_rating_row(a.as_posix())["user_total"] == 7.5  # 评分保留
    lib.add_source(root)
    assert lib.db.get_rating_row(a.as_posix())["user_total"] == 7.5


def test_same_content_shows_once_per_view(lib, tmp_path, root):
    other = tmp_path / "other"
    write_card(root, "a.json", name="Same")
    write_card(root, "a_copy.json", name="Same")
    write_card(other, "elsewhere.json", name="Same")
    write_card(other, "unique.json", name="Unique")
    lib.open([root, other])
    assert lib.db.count() == 4
    assert lib.list_cards().total == 2 and sorted(c["name"] for c in lib.list_cards().items) == ["Same", "Unique"]
    assert lib.search("Same", category=None).total == 1
    cats = lib.categories()
    assert cats["total"] == 2 and cats["items"][0]["count"] == 2


# ---------- 搜索 ----------
def test_chinese_search(lib, root):
    write_card(root, "1.json", name="魔法少女小圆", creator="虚渊玄", tags=["奇幻"], description="契约少女")
    write_card(root, "s/2.json", name="Detective Holmes", creator="Doyle", tags=["推理"],
               description="维多利亚时代的侦探", first_mes="我是福尔摩斯")
    lib.open([root])
    names = lambda q, **kw: [c["name"] for c in lib.search(q, **kw).items]  # noqa: E731
    assert names("魔法少女") == ["魔法少女小圆"]       # 4 字 -> FTS trigram
    assert names("福尔摩斯") == ["Detective Holmes"]   # 命中开场白
    assert names("虚渊玄") == ["魔法少女小圆"]          # 作者
    assert names("推理") == ["Detective Holmes"]       # 2 字 -> LIKE 回退
    assert names("魔") == ["魔法少女小圆"]              # 1 字
    assert names("detective") == ["Detective Holmes"]  # 大小写不敏感
    assert names("魔法少女 虚渊玄") == ["魔法少女小圆"]  # 多词 AND
    assert names("魔法少女 推理") == []
    assert names("不存在的词汇") == []
    assert names('say "hi"') == []  # 引号不会弄坏查询


def test_search_reflects_update_and_removal(lib, root):
    write_card(root, "a.json", name="旧名字角色")
    lib.open([root])
    assert lib.search("旧名字").total == 1
    p = write_card(root, "a.json", name="全新称呼角色")
    bump(p)
    lib.scan()
    assert lib.search("旧名字").total == 0
    assert lib.search("全新称呼").total == 1


def test_removed_file_leaves_index(lib, root):
    write_card(root, "a.json", name="将被删除的卡")
    write_card(root, "keep.json", name="保留")
    lib.open([root])

    (root / "a.json").unlink()
    r = lib.scan()
    assert r.removed == 1
    assert lib.get_card_by_path(key(root, "a.json")) is None
    assert lib.search("将被删除").total == 0
    assert lib.list_cards().total == 1


def test_pagination_and_sort(lib, root):
    for i in range(25):
        write_card(root, f"c{i:02d}.json", name=f"card{i:02d}")
    lib.open([root])
    p1 = lib.list_cards(page=1, page_size=10)
    p3 = lib.list_cards(page=3, page_size=10)
    assert p1.total == 25 and len(p1.items) == 10 and len(p3.items) == 5
    assert p1.items[0]["name"] == "card00"
    d = lib.list_cards(page_size=3, sort="name", order="desc")
    assert [c["name"] for c in d.items] == ["card24", "card23", "card22"]
    with pytest.raises(ValueError):
        lib.list_cards(sort="path; DROP TABLE cards")


# ---------- 保存：冲突检查保留，备份不再有 ----------
def test_conflict_detection(lib, root):
    p = write_card(root, "a.json", name="A")
    lib.open([root])
    card = lib.get_card_by_path(p)

    ok = lib.check_conflict(p, card["mtime_ns"], card["hash"])
    assert not ok.conflict

    bump(p)  # 仅 touch：hash 相同
    assert not lib.check_conflict(p, card["mtime_ns"], card["hash"]).conflict
    assert lib.check_conflict(p, card["mtime_ns"]).conflict  # 只给 mtime 则视为冲突

    p.write_text('{"name": "external edit"}', encoding="utf-8")
    c = lib.check_conflict(p, card["mtime_ns"], card["hash"])
    assert c.conflict and c.reason == "modified" and c.current_hash != card["hash"]

    p.unlink()
    assert lib.check_conflict(p, card["mtime_ns"], card["hash"]).reason == "missing"


def test_save_card_bytes_writes_in_place_without_backup(lib, tmp_path, root):
    p = write_card(root, "a.json", name="A")
    lib.open([root])
    card = lib.get_card_by_path(p)
    before = {q for q in tmp_path.rglob("*") if q.is_file()}
    lib.save_card_bytes(p, b'{"name": "B"}', expected_mtime_ns=card["mtime_ns"], expected_hash=card["hash"])
    assert lib.get_card_by_path(p)["name"] == "B"
    new_files = {q for q in tmp_path.rglob("*") if q.is_file()} - before
    assert all(q.is_relative_to(tmp_path / "data") for q in new_files)  # 卡文件夹里没有多出任何文件

    p.write_text('{"name": "C"}', encoding="utf-8")  # 外部修改
    with pytest.raises(ConflictError):
        lib.save_card_bytes(p, b'{"name": "D"}', expected_mtime_ns=card["mtime_ns"],
                            expected_hash=card["hash"])
    assert p.read_text(encoding="utf-8") == '{"name": "C"}'


def test_path_outside_sources_rejected(lib, tmp_path, root):
    lib.open([root])
    with pytest.raises(ValueError):
        lib.abs_path(tmp_path / "outside.json")
    with pytest.raises(ValueError):
        lib.abs_path(root / ".." / "outside.json")


def test_backup_manager_still_works_standalone(tmp_path):
    """BackupManager 保留为独立工具，保存流程不再调用它。"""
    root = tmp_path / "cards"
    p = write_card(root, "sub/a.json", name="v0")
    mgr = BackupManager(root, keep=3)
    for i in range(7):
        mgr.backup("sub/a.json")
        p.write_text(f'{{"name": "v{i + 1}"}}', encoding="utf-8")
    baks = mgr.list_backups("sub/a.json")
    assert len(baks) == 3 and baks[0].path.suffix == ".json"
    assert mgr.backup("nope.json") is None
    original = baks[-1]
    data = original.path.read_bytes()
    pre = mgr.restore("sub/a.json", original.name)
    assert pre is not None and p.read_bytes() == data
    with pytest.raises(ValueError):
        mgr.backup("../outside.json")


# ---------- 缩略图与清空 ----------
def test_thumbnail_cache_lives_in_data_dir(lib, tmp_path, root):
    p = root / "pic.png"
    p.write_bytes(png_bytes())
    lib.open([root])
    cid = lib.get_card_by_path(p)["id"]

    t1 = lib.get_thumbnail(cid)
    assert t1.parent == tmp_path / "data" / "thumbs" and t1.suffix == ".webp"
    assert not (root / ".kabao").exists()
    with Image.open(t1) as im:
        assert im.format == "WEBP" and im.width == 360 and im.height == 540
    assert lib.thumbs.generated == 1

    mtime = t1.stat().st_mtime_ns
    t2 = lib.get_thumbnail(cid)
    assert t2 == t1 and lib.thumbs.generated == 1 and t2.stat().st_mtime_ns == mtime  # 命中

    p.write_bytes(png_bytes(color=(10, 200, 10)))  # 内容变 -> hash 变
    lib.refresh_file(p)
    t3 = lib.get_thumbnail(cid)
    assert t3 != t1 and lib.thumbs.generated == 2

    keep = {lib.get_card(cid)["hash"]}
    assert lib.thumbs.prune(keep) == 1 and not t1.exists() and t3.exists()


def test_small_image_not_upscaled(lib, root):
    (root / "s.png").write_bytes(png_bytes(100, 150))
    lib.open([root])
    t = lib.get_thumbnail(lib.get_card_by_path(key(root, "s.png"))["id"])
    with Image.open(t) as im:
        assert im.size == (100, 150)


def test_json_card_has_no_thumbnail(lib, root):
    write_card(root, "a.json", name="A")
    lib.open([root])
    assert lib.get_thumbnail(lib.get_card_by_path(key(root, "a.json"))["id"]) is None


def test_clear_index_keeps_sources_ratings_and_files(lib, tmp_path, root):
    a = write_card(root, "a.json", name="A")
    (root / "pic.png").write_bytes(png_bytes())
    lib.open([root])
    cid = lib.get_card_by_path(root / "pic.png")["id"]
    lib.get_thumbnail(cid)
    lib.colors_dir.mkdir(exist_ok=True)
    (lib.colors_dir / "x.txt").write_text("#112233")
    h = lib.get_card_by_path(a)["hash"]
    lib.db.set_user_total(a.as_posix(), h, 6.0)
    files_before = sorted(p.name for p in root.rglob("*"))

    assert lib.clear_index() == 2
    assert lib.list_cards().total == 0 and lib.db.count() == 0 and lib.search("A").total == 0
    assert list((tmp_path / "data" / "thumbs").glob("*")) == [] and list(lib.colors_dir.glob("*")) == []
    assert [s.path for s in lib.sources] == [root.as_posix()]
    assert sorted(p.name for p in root.rglob("*")) == files_before
    assert lib.db.get_rating_row(a.as_posix())["user_total"] == 6.0

    r = lib.scan()
    assert r.added == 2 and lib.list_cards().total == 2
    assert lib.db.get_rating_row(a.as_posix())["user_total"] == 6.0


def test_rating_relinks_by_hash_when_file_moved_during_clear(lib, root):
    a = write_card(root, "a.json", name="A")
    lib.open([root])
    lib.db.set_user_total(a.as_posix(), lib.get_card_by_path(a)["hash"], 8.0)
    lib.clear_index()
    a.rename(root / "moved.json")
    lib.scan()
    assert lib.db.get_rating_row(key(root, "moved.json"))["user_total"] == 8.0
    assert lib.db.get_rating_row(a.as_posix()) is None


# ---------- 首页分类：全部 / 收藏 / 未分类 / 用户分类 ----------
def names_in(lib, cat):
    return sorted(c["name"] for c in lib.list_cards(cat).items)


def counts(lib):
    return {i["key"]: i["count"] for i in lib.categories()["items"]}


def test_fixed_categories_and_no_source_categories(lib, tmp_path, root):
    write_card(root, "a.json", name="A")
    write_card(tmp_path / "other", "b.json", name="B")
    lib.open([root, tmp_path / "other"])
    cats = lib.categories()
    assert [(i["key"], i["name"]) for i in cats["items"]] == [
        ("all", "全部"), ("unsorted", "未分类"), ("favorites", "收藏")]
    assert counts(lib) == {"all": 2, "favorites": 0, "unsorted": 2}


def test_collection_crud_and_names(lib, root):
    write_card(root, "a.json", name="A")
    lib.open([root])
    c1 = lib.create_collection("喜欢")
    c2 = lib.create_collection("待玩")
    assert [i["name"] for i in lib.categories()["items"][3:]] == ["喜欢", "待玩"]
    assert [i["key"] for i in lib.categories()["items"][3:]] == [f"c{c1['id']}", f"c{c2['id']}"]
    with pytest.raises(ValueError):
        lib.create_collection("喜欢")
    lib.create_collection("ABC")
    with pytest.raises(ValueError):
        lib.create_collection("abc")  # 不分大小写
    assert lib.rename_collection(c2["id"], "已玩")
    with pytest.raises(ValueError):
        lib.rename_collection(c2["id"], "喜欢")
    assert lib.rename_collection(c1["id"], "喜欢")  # 改成自己的名字不算重名
    assert not lib.rename_collection(999, "x")
    assert lib.delete_collection(c1["id"]) and not lib.delete_collection(c1["id"])
    assert [i["name"] for i in lib.categories()["items"][3:]][0] == "已玩"


def test_card_in_and_out_of_collections_and_unsorted(lib, root):
    a = write_card(root, "a.json", name="A")
    write_card(root, "b.json", name="B")
    write_card(root, "c.json", name="C")
    lib.open([root])
    ca = lib.get_card_by_path(a)
    x = lib.create_collection("X")["id"]
    y = lib.create_collection("Y")["id"]
    assert counts(lib)["unsorted"] == 3

    lib.set_card_collections(ca, [x, y])  # 一张卡可同时在多个分类里
    assert names_in(lib, f"c{x}") == ["A"] and names_in(lib, f"c{y}") == ["A"]
    assert names_in(lib, "unsorted") == ["B", "C"]
    assert lib.db.card_shelf(a.as_posix())["collections"] == [x, y]
    assert counts(lib) == {"all": 3, "favorites": 0, "unsorted": 2, f"c{x}": 1, f"c{y}": 1}

    lib.set_card_collections(ca, [y])  # 移出一个
    assert names_in(lib, f"c{x}") == [] and names_in(lib, f"c{y}") == ["A"]
    lib.set_card_collections(ca, [y, 12345])  # 不存在的分类忽略
    assert lib.db.card_shelf(a.as_posix())["collections"] == [y]

    lib.set_card_collections(ca, [])  # 全部移出 -> 回到未分类
    assert names_in(lib, "unsorted") == ["A", "B", "C"]
    lib.set_card_collections(ca, [x])
    lib.delete_collection(x)  # 删分类不删卡，卡回到未分类
    assert names_in(lib, "unsorted") == ["A", "B", "C"] and lib.list_cards().total == 3
    assert a.exists()
    with pytest.raises(ValueError):
        lib.list_cards(f"c{x}x")


def test_favorites(lib, root):
    a = write_card(root, "a.json", name="A")
    write_card(root, "b.json", name="B")
    lib.open([root])
    ca = lib.get_card_by_path(a)
    lib.set_favorite(ca, True)
    lib.set_favorite(ca, True)
    assert names_in(lib, "favorites") == ["A"] and counts(lib)["favorites"] == 1
    assert names_in(lib, "unsorted") == ["A", "B"]  # 收藏不等于归类
    assert lib.db.card_shelf(a.as_posix())["favorite"] is True
    assert lib.search("A", category="favorites").total == 1
    assert lib.search("B", category="favorites").total == 0
    lib.set_favorite(ca, False)
    assert names_in(lib, "favorites") == []


def test_shelf_survives_clear_and_rescan(lib, root):
    a = write_card(root, "a.json", name="A")
    b = write_card(root, "b.json", name="B")
    lib.open([root])
    x = lib.create_collection("X")["id"]
    lib.set_favorite(lib.get_card_by_path(a), True)
    lib.set_card_collections(lib.get_card_by_path(a), [x])
    lib.set_card_collections(lib.get_card_by_path(b), [x])

    lib.clear_index()
    assert lib.list_cards().total == 0 and counts(lib)["all"] == 0
    assert [i["name"] for i in lib.categories()["items"][3:]] == ["X"]  # 分类本身还在
    lib.scan()
    assert names_in(lib, "favorites") == ["A"] and names_in(lib, f"c{x}") == ["A", "B"]
    assert names_in(lib, "unsorted") == []


def test_shelf_follows_rename_by_hash_and_edit_by_path(lib, root):
    a = write_card(root, "a.json", name="A")
    lib.open([root])
    x = lib.create_collection("X")["id"]
    lib.set_favorite(lib.get_card_by_path(a), True)
    lib.set_card_collections(lib.get_card_by_path(a), [x])

    p = write_card(root, "a.json", name="A edited")  # 先改内容：按路径跟着走，hash 同步更新
    bump(p)
    lib.scan()
    assert names_in(lib, f"c{x}") == ["A edited"]
    p.rename(root / "renamed.json")  # 再改名：按 hash 接回
    lib.scan()
    assert names_in(lib, f"c{x}") == ["A edited"] and names_in(lib, "favorites") == ["A edited"]


def test_same_content_copy_shares_shelf_and_never_shows_as_unsorted(lib, root):
    a = write_card(root, "a.json", name="A")
    lib.open([root])
    x = lib.create_collection("X")["id"]
    lib.set_card_collections(lib.get_card_by_path(a), [x])
    lib.set_favorite(lib.get_card_by_path(a), True)
    write_card(root, "copy.json", name="A")  # 同内容副本
    lib.scan()
    assert lib.db.card_shelf(key(root, "copy.json")) == {"favorite": True, "collections": [x]}
    assert names_in(lib, "unsorted") == [] and names_in(lib, f"c{x}") == ["A"]
    assert lib.list_cards(f"c{x}").total == 1 and lib.list_cards("favorites").total == 1
    lib.set_card_collections(lib.get_card_by_path(key(root, "copy.json")), [])  # 从副本上取消，两份一起出来
    assert names_in(lib, f"c{x}") == [] and names_in(lib, "unsorted") == ["A"]


def test_different_content_does_not_inherit_shelf(lib, root):
    a = write_card(root, "a.json", name="A")
    write_card(root, "b.json", name="B")
    lib.open([root])
    x = lib.create_collection("X")["id"]
    lib.set_card_collections(lib.get_card_by_path(a), [x])
    assert lib.db.card_shelf(key(root, "b.json")) == {"favorite": False, "collections": []}
    assert names_in(lib, "unsorted") == ["B"]


# ---------- watcher ----------
class Collector:
    def __init__(self):
        self.batches = []
        self.ev = threading.Event()

    def __call__(self, changes):
        self.batches.append(changes)
        self.ev.set()

    def wait(self, timeout=8.0):
        ok = self.ev.wait(timeout)
        self.ev.clear()
        return ok


def test_watcher_debounce_and_sync(lib, root):
    write_card(root, "seed.json", name="Seed")
    lib.open([root])
    col = Collector()
    lib.start_watching(col)
    time.sleep(0.3)

    # 连续多次写同一文件 -> 去抖后只回调一次
    for i in range(5):
        write_card(root, "new.json", name=f"新卡{i}")
        time.sleep(0.03)
    assert col.wait()
    time.sleep(0.5)
    assert len(col.batches) == 1
    assert col.batches[0].upserted.count(key(root, "new.json")) == 1
    assert lib.get_card_by_path(key(root, "new.json"))["name"] == "新卡4"

    # 删除
    (root / "new.json").unlink()
    assert col.wait()
    assert lib.get_card_by_path(key(root, "new.json")) is None
    assert col.batches[-1].removed == [key(root, "new.json")]

    # 改名
    os.rename(root / "seed.json", root / "renamed.json")
    assert col.wait()
    time.sleep(0.4)
    assert lib.get_card_by_path(key(root, "seed.json")) is None
    assert lib.get_card_by_path(key(root, "renamed.json"))["name"] == "Seed"

    # 新子文件夹里的卡
    write_card(root, "newdir/x.json", name="X")
    assert col.wait()
    time.sleep(0.4)
    assert lib.get_card_by_path(key(root, "newdir/x.json")) is not None

    lib.stop_watching()


def test_watcher_covers_new_sources_and_single_files(lib, tmp_path, root):
    solo_dir = tmp_path / "downloads"
    solo = write_card(solo_dir, "solo.json", name="Solo")
    lib.open([root])
    col = Collector()
    lib.start_watching(col)
    lib.add_source(solo)  # 加来源后监听要跟着重建
    time.sleep(0.3)

    write_card(solo_dir, "stranger.json", name="Stranger")  # 单卡所在文件夹里的其他文件不是来源
    assert not col.wait(timeout=1.0)
    assert lib.get_card_by_path(solo_dir / "stranger.json") is None

    write_card(solo_dir, "solo.json", name="Solo2")
    assert col.wait()
    assert lib.get_card_by_path(solo)["name"] == "Solo2"

    write_card(root, "later.json", name="Later")
    assert col.wait()
    assert lib.get_card_by_path(key(root, "later.json")) is not None
    lib.stop_watching()


def test_watcher_ignores_dot_folders_and_tmp(lib, root):
    lib.open([root])
    col = Collector()
    lib.start_watching(col)
    time.sleep(0.3)
    write_card(root, ".bak_history/x.json", name="hidden")
    (root / ".a.json.abcd1234.tmp").write_bytes(b"partial")
    (root / "b.png.tmp").write_bytes(b"partial")
    assert not col.wait(timeout=1.0)
    assert col.batches == []
    lib.stop_watching()
    assert lib.list_cards().total == 0


def test_watcher_start_stop(lib, root):
    lib.open([root])
    col = Collector()
    lib.start_watching(col)
    lib.stop_watching()
    write_card(root, "late.json", name="Late")
    assert not col.wait(timeout=1.0)
    lib.start_watching(col)  # 可重新启动
    time.sleep(0.3)
    write_card(root, "again.json", name="Again")
    assert col.wait()
    lib.stop_watching()
