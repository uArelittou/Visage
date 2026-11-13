"""SQLite 卡库索引。数据文件位于用户数据目录的 library.db（不在用户的卡文件夹里），WAL 模式。

单连接 + RLock：FastAPI 线程池、watcher 线程、扫描线程共用同一个 Database 实例。
卡的路径（path）是规范化的绝对路径，正斜杠（"D:/cards/a/b.png"）。
source 是卡所属的来源（文件夹或单卡文件的路径）；sub 是卡在来源文件夹里的子路径，只作记录。
首页分类（收藏、用户分类）是千面录自己的数据，和评分一样按卡路径挂、按内容 hash 找回，不算扫描数据。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    path           TEXT NOT NULL UNIQUE,
    source         TEXT NOT NULL,
    sub            TEXT NOT NULL DEFAULT '',
    file_name      TEXT NOT NULL,
    ext            TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    creator        TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '[]',
    description    TEXT NOT NULL DEFAULT '',
    greeting_count INTEGER NOT NULL DEFAULT 0,
    lorebook_count INTEGER NOT NULL DEFAULT 0,
    regex_count    INTEGER NOT NULL DEFAULT 0,
    script_count   INTEGER NOT NULL DEFAULT 0,
    spec           TEXT NOT NULL DEFAULT '',
    mtime_ns       INTEGER NOT NULL,
    size           INTEGER NOT NULL,
    hash           TEXT NOT NULL,
    is_broken      INTEGER NOT NULL DEFAULT 0,
    error          TEXT NOT NULL DEFAULT '',
    scanned_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_source ON cards(source);
CREATE INDEX IF NOT EXISTS idx_cards_hash ON cards(hash);

-- 评分按路径挂，不外键到 cards.id：清空卡库、改名、移除来源都会让 cards 行被删，外键级联会连评分一起删。
-- 路径对不上时由 relink_ratings 按 content_hash 把评分找回新路径。
CREATE TABLE IF NOT EXISTS card_ratings (
    path           TEXT PRIMARY KEY,
    content_hash   TEXT NOT NULL,
    ai_total       REAL,
    ai_result      TEXT,
    model          TEXT NOT NULL DEFAULT '',
    rubric_version INTEGER,
    rated_at       REAL,
    user_total     REAL,
    user_rated_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_card_ratings_hash ON card_ratings(content_hash);

CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_cards (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    PRIMARY KEY (collection_id, path)
);
CREATE INDEX IF NOT EXISTS idx_collection_cards_path ON collection_cards(path);
CREATE INDEX IF NOT EXISTS idx_collection_cards_hash ON collection_cards(content_hash);
CREATE TABLE IF NOT EXISTS favorites (
    path         TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_favorites_hash ON favorites(content_hash);
CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, creator, tags, description, greetings,
    tokenize = 'trigram'
);
"""

SORT_COLUMNS = {
    "name": "name COLLATE NOCASE",
    "creator": "creator COLLATE NOCASE",
    "mtime": "mtime_ns",
    "size": "size",
    "file_name": "file_name COLLATE NOCASE",
    "lorebook": "lorebook_count",
    "greetings": "greeting_count",
}

LIST_COLUMNS = (
    "id, path, source, sub, file_name, ext, name, creator, tags, description, "
    "greeting_count, lorebook_count, regex_count, script_count, spec, "
    "mtime_ns, size, hash, is_broken, error"
)


@dataclass
class CardRecord:
    """写入 cards 表的一行。search_greetings 只进 FTS，不落 cards 表。"""

    path: str
    source: str
    mtime_ns: int
    size: int
    hash: str
    sub: str = ""
    name: str = ""
    creator: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    greeting_count: int = 0
    lorebook_count: int = 0
    regex_count: int = 0
    script_count: int = 0
    spec: str = ""
    is_broken: bool = False
    error: str = ""
    search_greetings: str = ""

    @property
    def file_name(self) -> str:
        return self.path.rpartition("/")[2]


@dataclass
class Page:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
    d["is_broken"] = bool(d["is_broken"])
    return d


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._tx_depth = 0
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _migrate(self) -> None:
        """v2 及更早的索引按「相对卡库根目录的路径」建，和现在的绝对路径不兼容。索引可以重建，直接丢掉；
        评分表只改列名，旧路径会变成无主评分，扫描时按内容 hash 接回。"""
        def columns(table: str) -> set[str]:
            return {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}

        if "rel_path" in columns("cards"):
            self._conn.executescript(
                "DROP TABLE cards; DROP TABLE IF EXISTS cards_fts; DROP TABLE IF EXISTS folders;"
            )
        if "rel_path" in columns("card_ratings"):
            self._conn.execute("ALTER TABLE card_ratings RENAME COLUMN rel_path TO path")

    # ---- 基础 ----
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """可嵌套；仅最外层 BEGIN/COMMIT。"""
        with self._lock:
            outer = self._tx_depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._tx_depth += 1
            try:
                yield
            except BaseException:
                self._tx_depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._tx_depth -= 1
                if outer:
                    self._conn.execute("COMMIT")

    def _q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    # ---- 写入 ----
    def upsert(self, rec: CardRecord) -> int:
        file_name = rec.file_name
        ext = Path(file_name).suffix.lower()
        with self.transaction():
            row = self._conn.execute(
                """
                INSERT INTO cards (path, source, sub, file_name, ext, name, creator, tags,
                    description, greeting_count, lorebook_count, regex_count, script_count,
                    spec, mtime_ns, size, hash, is_broken, error, scanned_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    source=excluded.source, sub=excluded.sub,
                    file_name=excluded.file_name, ext=excluded.ext,
                    name=excluded.name, creator=excluded.creator, tags=excluded.tags,
                    description=excluded.description, greeting_count=excluded.greeting_count,
                    lorebook_count=excluded.lorebook_count, regex_count=excluded.regex_count,
                    script_count=excluded.script_count, spec=excluded.spec,
                    mtime_ns=excluded.mtime_ns, size=excluded.size, hash=excluded.hash,
                    is_broken=excluded.is_broken, error=excluded.error,
                    scanned_at=excluded.scanned_at
                RETURNING id
                """,
                (
                    rec.path, rec.source, rec.sub, file_name, ext, rec.name,
                    rec.creator, json.dumps(rec.tags, ensure_ascii=False), rec.description,
                    rec.greeting_count, rec.lorebook_count, rec.regex_count,
                    rec.script_count, rec.spec, rec.mtime_ns, rec.size, rec.hash,
                    int(rec.is_broken), rec.error, time.time(),
                ),
            ).fetchone()
            card_id = row["id"]
            for table in ("card_ratings", "collection_cards", "favorites"):
                self._conn.execute(
                    f"UPDATE {table} SET content_hash=? WHERE path=? AND content_hash<>?",
                    (rec.hash, rec.path, rec.hash),
                )
            self._conn.execute("DELETE FROM cards_fts WHERE rowid=?", (card_id,))
            self._conn.execute(
                "INSERT INTO cards_fts(rowid, name, creator, tags, description, greetings)"
                " VALUES (?,?,?,?,?,?)",
                (
                    card_id, rec.name, rec.creator, " ".join(rec.tags),
                    rec.description, rec.search_greetings,
                ),
            )
        return card_id

    def upsert_many(self, recs: Iterable[CardRecord]) -> None:
        with self.transaction():
            for r in recs:
                self.upsert(r)

    def remove(self, path: str) -> bool:
        return self.remove_many([path]) > 0

    def remove_many(self, paths: Iterable[str]) -> int:
        n = 0
        with self.transaction():
            for p in paths:
                row = self._conn.execute(
                    "SELECT id FROM cards WHERE path=?", (p,)
                ).fetchone()
                if row is None:
                    continue
                self._conn.execute("DELETE FROM cards_fts WHERE rowid=?", (row["id"],))
                self._conn.execute("DELETE FROM cards WHERE id=?", (row["id"],))
                n += 1
        return n

    def remove_source(self, source: str) -> int:
        """移除某个来源下的全部卡记录。只动索引，评分行保留。"""
        with self.transaction():
            ids = [r["id"] for r in self._conn.execute("SELECT id FROM cards WHERE source=?", (source,))]
            for i in ids:
                self._conn.execute("DELETE FROM cards_fts WHERE rowid=?", (i,))
                self._conn.execute("DELETE FROM cards WHERE id=?", (i,))
        return len(ids)

    def clear_index(self) -> int:
        """清空卡索引（cards + 全文索引）。评分表不动。"""
        with self.transaction():
            n = self._conn.execute("SELECT COUNT(*) AS c FROM cards").fetchone()["c"]
            self._conn.execute("DELETE FROM cards_fts")
            self._conn.execute("DELETE FROM cards")
        return n

    def touch_stat(self, path: str, mtime_ns: int, size: int) -> None:
        """内容 hash 未变、仅 mtime 变化时只更新文件状态。"""
        with self._lock:
            self._conn.execute(
                "UPDATE cards SET mtime_ns=?, size=? WHERE path=?",
                (mtime_ns, size, path),
            )

    def set_location(self, path: str, source: str, sub: str) -> None:
        """文件没变，只是归属的来源变了（子来源被父文件夹合并）。"""
        with self._lock:
            self._conn.execute(
                "UPDATE cards SET source=?, sub=? WHERE path=?", (source, sub, path)
            )

    def move_source(self, old: str, new: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE cards SET source=? WHERE source=?", (new, old))

    # ---- 收藏与用户分类 ----
    # 这些数据和评分一样不属于扫描数据：清空卡库时保留，重扫后接回。归属按内容 hash 判定，
    # 所以改名、移动后仍在；同内容的副本一起算，不会出现「卡在分类里，副本却显示在未分类」。
    # 卡被编辑时 content_hash 跟着路径更新（见 upsert）。
    def list_collections(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT id, name FROM collections ORDER BY id")]

    def get_collection(self, collection_id: int) -> dict[str, Any] | None:
        rows = self._q("SELECT id, name FROM collections WHERE id=?", (collection_id,))
        return dict(rows[0]) if rows else None

    def _name_taken(self, name: str, except_id: int | None = None) -> bool:
        return any(
            r["name"].casefold() == name.casefold() and r["id"] != except_id
            for r in self._q("SELECT id, name FROM collections")
        )

    def create_collection(self, name: str) -> int:
        with self.transaction():
            if self._name_taken(name):
                raise ValueError("name_exists")
            return self._conn.execute(
                "INSERT INTO collections(name, created_at) VALUES (?,?)", (name, time.time())
            ).lastrowid

    def rename_collection(self, collection_id: int, name: str) -> bool:
        with self.transaction():
            if self._name_taken(name, collection_id):
                raise ValueError("name_exists")
            return self._conn.execute(
                "UPDATE collections SET name=? WHERE id=?", (name, collection_id)
            ).rowcount > 0

    def delete_collection(self, collection_id: int) -> bool:
        """只删分类本身和它的归属记录，不碰任何卡。"""
        with self.transaction():
            self._conn.execute("DELETE FROM collection_cards WHERE collection_id=?", (collection_id,))
            return self._conn.execute(
                "DELETE FROM collections WHERE id=?", (collection_id,)
            ).rowcount > 0

    def card_shelf(self, path: str) -> dict[str, Any]:
        """这张卡是否收藏、属于哪些用户分类。"""
        with self._lock:
            h = self._card_hash(path)
            fav = self._conn.execute(
                "SELECT 1 FROM favorites WHERE path=? OR content_hash=?", (path, h)
            ).fetchone()
            ids = [
                r["collection_id"]
                for r in self._conn.execute(
                    "SELECT DISTINCT collection_id FROM collection_cards WHERE path=? OR content_hash=?"
                    " ORDER BY collection_id", (path, h),
                )
            ]
        return {"favorite": fav is not None, "collections": ids}

    def _card_hash(self, path: str) -> str | None:
        row = self._conn.execute("SELECT hash FROM cards WHERE path=?", (path,)).fetchone()
        return row["hash"] if row else None

    def set_favorite(self, path: str, content_hash: str, value: bool) -> None:
        with self._lock:
            if value:
                self._conn.execute(
                    "INSERT INTO favorites(path, content_hash) VALUES (?,?)"
                    " ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash",
                    (path, content_hash),
                )
            else:
                self._conn.execute("DELETE FROM favorites WHERE path=? OR content_hash=?", (path, content_hash))

    def set_card_collections(self, path: str, content_hash: str, collection_ids: list[int]) -> None:
        """把这张卡的用户分类整体设为 collection_ids（不存在的分类忽略）。"""
        with self.transaction():
            valid = {r["id"] for r in self._conn.execute("SELECT id FROM collections")}
            self._conn.execute(
                "DELETE FROM collection_cards WHERE path=? OR content_hash=?", (path, content_hash)
            )
            for cid in sorted({c for c in collection_ids if c in valid}):
                self._conn.execute(
                    "INSERT INTO collection_cards(collection_id, path, content_hash) VALUES (?,?,?)",
                    (cid, path, content_hash),
                )

    # 视图范围：key 为 None/"all"、"favorites"、"unsorted" 或 "c<分类id>"
    def _member(self, key: str | None, alias: str) -> tuple[str, list[Any]]:
        if key in (None, "", "all"):
            return "1", []
        if key == "favorites":
            return f"EXISTS (SELECT 1 FROM favorites fv WHERE fv.content_hash = {alias}.hash)", []
        if key == "unsorted":
            return f"NOT EXISTS (SELECT 1 FROM collection_cards cm WHERE cm.content_hash = {alias}.hash)", []
        if key.startswith("c") and key[1:].isdigit():
            return (
                f"EXISTS (SELECT 1 FROM collection_cards cm WHERE cm.content_hash = {alias}.hash"
                " AND cm.collection_id = ?)", [int(key[1:])],
            )
        raise ValueError(f"unknown category: {key}")

    def view_counts(self, collection_ids: list[int]) -> dict[str, int]:
        """首页各视图的数量，同内容的卡在一个视图里只算一张。"""
        keys = ["all", "favorites", "unsorted", *[f"c{i}" for i in collection_ids]]
        out = {}
        for k in keys:
            cond, params = self._member(k, "c")
            out[k] = self._q(
                f"SELECT COUNT(DISTINCT hash) AS n FROM cards c WHERE {cond}", params
            )[0]["n"]
        return out

    def source_counts(self) -> dict[str, int]:
        """各来源下索引到的文件数（不去重）。"""
        return {
            r["source"]: r["c"]
            for r in self._q("SELECT source, COUNT(*) AS c FROM cards GROUP BY source")
        }

    # ---- 查询 ----
    def get_card(self, card_id: int) -> dict[str, Any] | None:
        rows = self._q(f"SELECT {LIST_COLUMNS} FROM cards WHERE id=?", (card_id,))
        return _row_to_dict(rows[0]) if rows else None

    def get_by_path(self, path: str) -> dict[str, Any] | None:
        rows = self._q(f"SELECT {LIST_COLUMNS} FROM cards WHERE path=?", (path,))
        return _row_to_dict(rows[0]) if rows else None

    def snapshot(self) -> dict[str, tuple[int, int, str, str]]:
        """path -> (mtime_ns, size, hash, source)，供增量扫描比对。"""
        return {
            r["path"]: (r["mtime_ns"], r["size"], r["hash"], r["source"])
            for r in self._q("SELECT path, mtime_ns, size, hash, source FROM cards")
        }

    def count(self) -> int:
        """索引里的文件数，内容相同的卡各算一张。"""
        return self._q("SELECT COUNT(*) AS c FROM cards")[0]["c"]

    def unique_count(self) -> int:
        """首页「全部」显示的数量：内容相同的卡只算一张。"""
        return self._q("SELECT COUNT(DISTINCT hash) AS c FROM cards")[0]["c"]

    def _scope(self, alias: str, category: str | None) -> tuple[list[str], list[Any]]:
        """视图范围加去重：范围内内容 hash 相同的卡只留 id 最小的一张。
        范围按当前视图算，所以一张卡的副本在别处，不会让它从自己所在的视图里消失。"""
        cond, params = self._member(category, alias)
        inner, inner_params = self._member(category, "d")
        dedupe = (
            f"{alias}.id = (SELECT MIN(d.id) FROM cards d WHERE d.hash = {alias}.hash AND {inner})"
        )
        return [cond, dedupe], [*params, *inner_params]

    def list_cards(
        self,
        category: str | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
        sort: str = "name",
        order: str = "asc",
    ) -> Page:
        page = max(1, page)
        page_size = max(1, min(page_size, 500))
        sort_col = SORT_COLUMNS.get(sort)
        if sort_col is None:
            raise ValueError(f"unsupported sort: {sort}")
        direction = "DESC" if order.lower() == "desc" else "ASC"
        conds, params = self._scope("c", category)
        where = " AND ".join(conds)
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM cards c WHERE {where}", params
            ).fetchone()["c"]
            rows = self._conn.execute(
                f"SELECT {LIST_COLUMNS} FROM cards c WHERE {where} "
                f"ORDER BY {sort_col} {direction}, id LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return Page([_row_to_dict(r) for r in rows], total, page, page_size)

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Page:
        """空格分隔的多个词为 AND。>=3 字符的词走 FTS5 trigram，更短的词走 LIKE
        （trigram 无法索引 1~2 个字符，如单个汉字或两字词）。"""
        page = max(1, page)
        page_size = max(1, min(page_size, 500))
        tokens = query.split()
        if not tokens:
            return self.list_cards(category, page=page, page_size=page_size)
        fts_tokens = [t for t in tokens if len(t) >= 3]
        short_tokens = [t for t in tokens if len(t) < 3]

        conds: list[str] = []
        params: list[Any] = []
        if fts_tokens:
            match = " AND ".join('"' + t.replace('"', '""') + '"' for t in fts_tokens)
            conds.append("f.cards_fts MATCH ?")
            params.append(match)
        for t in short_tokens:
            like = "%" + _like_escape(t) + "%"
            conds.append(
                "(" + " OR ".join(
                    f"f.{c} LIKE ? ESCAPE '\\'"
                    for c in ("name", "creator", "tags", "description", "greetings")
                ) + ")"
            )
            params.extend([like] * 5)
        scope, sparams = self._scope("c", category)
        conds.extend(scope)
        params.extend(sparams)
        where = " AND ".join(conds)
        order = "ORDER BY bm25(cards_fts), c.id" if fts_tokens else "ORDER BY c.name COLLATE NOCASE, c.id"
        cols = ", ".join("c." + col.strip() for col in LIST_COLUMNS.split(","))
        base = "FROM cards_fts f JOIN cards c ON c.id = f.rowid"
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS n {base} WHERE {where}", params
            ).fetchone()["n"]
            rows = self._conn.execute(
                f"SELECT {cols} {base} WHERE {where} {order} LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return Page([_row_to_dict(r) for r in rows], total, page, page_size)

    # ---- 评分 ----
    # 评分行以卡路径为键；卡被改过时 content_hash 跟着更新，这样「先改内容再改名」也能找回。
    def get_rating_row(self, path: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM card_ratings WHERE path=?", (path,))
        return dict(rows[0]) if rows else None

    def save_ai_rating(
        self, path: str, content_hash: str, *, ai_total: float, ai_result: str,
        model: str, rubric_version: int,
    ) -> None:
        """只写 AI 部分，不碰已有的 user_total。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO card_ratings(path, content_hash, ai_total, ai_result, model,"
                " rubric_version, rated_at) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash,"
                " ai_total=excluded.ai_total, ai_result=excluded.ai_result, model=excluded.model,"
                " rubric_version=excluded.rubric_version, rated_at=excluded.rated_at",
                (path, content_hash, ai_total, ai_result, model, rubric_version, time.time()),
            )

    def set_user_total(self, path: str, content_hash: str, total: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO card_ratings(path, content_hash, user_total, user_rated_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET user_total=excluded.user_total,"
                " user_rated_at=excluded.user_rated_at, content_hash=excluded.content_hash",
                (path, content_hash, total, time.time()),
            )

    def clear_user_total(self, path: str) -> None:
        with self.transaction():
            self._conn.execute(
                "UPDATE card_ratings SET user_total=NULL, user_rated_at=NULL WHERE path=?",
                (path,),
            )
            # 没有 AI 评分时这行已经没有内容，不留空壳
            self._conn.execute(
                "DELETE FROM card_ratings WHERE path=? AND ai_result IS NULL", (path,)
            )

    def relink_ratings(self) -> int:
        """文件改名、移动或清空重扫后 cards 行换了 path，把失去归属的评分按内容哈希接到新路径上。

        只接管「没有评分」的同哈希卡，避免覆盖别的卡自己的评分。"""
        moved = 0
        with self.transaction():
            orphans = self._conn.execute(
                "SELECT path, content_hash FROM card_ratings r"
                " WHERE NOT EXISTS (SELECT 1 FROM cards c WHERE c.path = r.path)"
            ).fetchall()
            for o in orphans:
                target = self._conn.execute(
                    "SELECT c.path FROM cards c WHERE c.hash=? AND NOT EXISTS"
                    " (SELECT 1 FROM card_ratings r2 WHERE r2.path = c.path)"
                    " ORDER BY c.id LIMIT 1",
                    (o["content_hash"],),
                ).fetchone()
                if target is not None:
                    self._conn.execute(
                        "UPDATE card_ratings SET path=? WHERE path=?",
                        (target["path"], o["path"]),
                    )
                    moved += 1
        return moved