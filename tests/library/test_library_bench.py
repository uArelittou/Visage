"""基准：1000 条记录分页查询 < 50ms（含按内容去重）。运行 `pytest -s` 可看到数字。"""
import statistics
import time

from backend.library.db import CardRecord, Database


def make_db(tmp_path, n=1000, groups=20):
    db = Database(tmp_path / "bench.db")
    recs = []
    for i in range(n):
        recs.append(CardRecord(
            path=f"D:/cards/g{i % groups:02d}/card{i:04d}.png", source="D:/cards",
            sub=f"g{i % groups:02d}", mtime_ns=i, size=1000 + i, hash=f"{i:064x}",
            name=f"角色{i:04d}", creator=f"作者{i % 37}", tags=["标签甲", "标签乙"],
            description="这是一段较长的简介。" * 20, greeting_count=3,
            search_greetings="你好，旅行者。" * 10,
        ))
    db.upsert_many(recs)
    for g in range(groups):
        cid = db.create_collection(f"分类{g}")
        for i in range(g, n, groups):
            db.set_card_collections(f"D:/cards/g{g:02d}/card{i:04d}.png", f"{i:064x}", [cid])
    return db


def _timeit(fn, rounds=50):
    ts = []
    for _ in range(rounds):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts), max(ts)


def test_pagination_under_50ms(tmp_path):
    db = make_db(tmp_path)
    assert db.count() == 1000 and db.unique_count() == 1000

    med, worst = _timeit(lambda: db.list_cards("c3", page=2, page_size=20))
    print(f"\n[bench] 用户分类分页(50张/类, page_size=20): 中位 {med:.2f}ms 最大 {worst:.2f}ms")
    assert worst < 50

    med_all, worst_all = _timeit(lambda: db.list_cards(None, page=10, page_size=50, sort="mtime", order="desc"))
    print(f"[bench] 全部(1000张)按 mtime 倒序分页: 中位 {med_all:.2f}ms 最大 {worst_all:.2f}ms")
    assert worst_all < 50

    med_u, worst_u = _timeit(lambda: db.list_cards("unsorted", page=1, page_size=50))
    print(f"[bench] 未分类: 中位 {med_u:.2f}ms 最大 {worst_u:.2f}ms")
    assert worst_u < 50

    med_s, worst_s = _timeit(lambda: db.search("旅行者", page_size=50), rounds=20)
    print(f"[bench] FTS 搜索(1000张): 中位 {med_s:.2f}ms 最大 {worst_s:.2f}ms")
    db.close()
