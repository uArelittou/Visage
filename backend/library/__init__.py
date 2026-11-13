"""卡库总入口：来源、索引、扫描、监听、缩略图的组合。

卡库不拥有任何卡文件，只在用户给的来源（文件夹或单张卡）上建索引。千面录自己的数据
（索引库、缩略图、封面色缓存）放在 data_dir，即用户数据目录，不写进用户的卡文件夹。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .backup import (
    BackupInfo, BackupManager, ConflictResult, atomic_write, check_conflict,
)
from .db import CardRecord, Database, Page
from .scanner import Loader, ScanResult, Scanner, is_card_file
from .sources import (
    AlreadyInLibrary, Location, Source, SourceError, canon, is_inside, locate, make_source,
    plan_add, same_path,
)
from .thumbs import ThumbCache
from .watcher import ChangeEvent, Watcher

__all__ = [
    "Library", "LibraryChanges", "AddResult", "Database", "CardRecord", "Page", "Scanner",
    "ScanResult", "Watcher", "ChangeEvent", "BackupManager", "BackupInfo", "ConflictResult",
    "ThumbCache", "atomic_write", "ConflictError", "Source", "SourceError", "AlreadyInLibrary",
]

ImageReader = Callable[[Path], bytes | None]


@dataclass
class LibraryChanges:
    """watcher 一批事件处理后的结果，传给 on_change 回调。"""

    upserted: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    full_rescan: ScanResult | None = None  # 目录级变化时触发


@dataclass
class AddResult:
    source: Source
    merged: list[Source]
    scan: ScanResult


def _default_image_reader(path: Path) -> bytes | None:
    if path.suffix.lower() in (".png", ".webp"):
        return path.read_bytes()
    return None


class Library:
    def __init__(
        self,
        data_dir: str | Path,
        loader: Loader,
        *,
        image_reader: ImageReader | None = None,
        debounce: float = 0.5,
    ):
        self.data_dir = Path(os.path.abspath(data_dir))
        self.loader = loader
        self.image_reader = image_reader or _default_image_reader
        self.debounce = debounce
        self.sources: list[Source] = []
        self.db: Database | None = None
        self.scanner: Scanner | None = None
        self.thumbs = ThumbCache(self.data_dir / "thumbs")
        self.colors_dir = self.data_dir / "colors"
        self._watcher: Watcher | None = None
        self._watching = False
        self._on_change: Callable[[LibraryChanges], None] | None = None
        self._scan_lock = threading.RLock()

    # ---- 生命周期 ----
    def open(self, sources: Iterable[str | Path] = ()) -> ScanResult:
        """建库并对给定来源做一次增量扫描。来源路径暂时不存在也保留，扫描时当作空。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "library.db")
        self.scanner = Scanner(self.db, self.loader, lambda: self.sources, self._locate, self.data_dir)
        self.sources = []
        for p in sources:
            s = make_source(p)
            if not any(same_path(x.path, s.path) for x in self.sources):
                self.sources.append(s)
        return self.scan()

    def close(self) -> None:
        self.stop_watching()
        if self.db is not None:
            self.db.close()
            self.db = None

    def __enter__(self) -> "Library":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _need_db(self) -> Database:
        if self.db is None or self.scanner is None:
            raise RuntimeError("Library is not open")
        return self.db

    # ---- 来源 ----
    def _locate(self, path: str, is_dir: bool = False) -> Location | None:
        if is_inside(path, self.data_dir.as_posix()):
            return None
        return locate(self.sources, path, is_dir)

    def add_source(self, path: str | Path) -> AddResult:
        """把文件夹或单张卡加入来源并原地索引。已被现有来源覆盖时抛 AlreadyInLibrary；
        新来源是现有来源的父文件夹时，子来源并入它。"""
        self._need_db()
        with self._scan_lock:
            source, merged = plan_add(self.sources, path)
            if not source.is_dir:
                try:
                    self.loader(Path(source.path))
                except Exception as e:  # noqa: BLE001  解析失败的原因对用户有用
                    raise SourceError("not_a_card", f"不是可识别的角色卡: {e}") from None
            gone = {s.path for s in merged}
            self.sources = [s for s in self.sources if s.path not in gone] + [source]
            res = self.scanner.scan([source])  # type: ignore[union-attr]
            for s in merged:
                # 先扫新来源让重叠的卡改挂到它名下；这里清掉子来源留下的、新来源没收进来的记录
                self.db.remove_source(s.path)  # type: ignore[union-attr]
            self._rewatch()
        return AddResult(source, merged, res)

    def remove_source(self, path: str | Path) -> Source | None:
        """把来源移出索引。只删索引记录，不碰任何卡文件，评分行保留。"""
        db = self._need_db()
        key = canon(path).as_posix()
        with self._scan_lock:
            found = next((s for s in self.sources if same_path(s.path, key)), None)
            if found is None:
                return None
            self.sources = [s for s in self.sources if s is not found]
            db.remove_source(found.path)
            self._rewatch()
        return found

    def replace_file_source(self, old: str, new: str) -> None:
        """单卡来源的文件换了路径（WebP 存成 PNG 后原文件被删），让来源跟过去。"""
        db = self._need_db()
        with self._scan_lock:
            self.sources = [
                Source(canon(new).as_posix(), False) if s.path == old else s for s in self.sources
            ]
            db.move_source(old, canon(new).as_posix())
            self._rewatch()

    def list_sources(self) -> list[dict[str, Any]]:
        counts = self._need_db().source_counts()
        return [
            {
                "path": s.path, "name": s.name, "kind": "folder" if s.is_dir else "file",
                "count": counts.get(s.path, 0), "missing": not os.path.exists(s.path),
            }
            for s in self.sources
        ]

    # ---- 首页分类：全部 / 收藏 / 未分类 + 用户分类 ----
    def categories(self) -> dict[str, Any]:
        db = self._need_db()
        cols = db.list_collections()
        counts = db.view_counts([c["id"] for c in cols])
        items = [
            {"key": "all", "name": "全部", "kind": "all", "count": counts["all"]},
            {"key": "unsorted", "name": "未分类", "kind": "unsorted", "count": counts["unsorted"]},
            {"key": "favorites", "name": "收藏", "kind": "favorites", "count": counts["favorites"]},
        ]
        items += [
            {"key": f"c{c['id']}", "id": c["id"], "name": c["name"], "kind": "user",
             "count": counts[f"c{c['id']}"]}
            for c in cols
        ]
        return {"total": counts["all"], "items": items}

    def create_collection(self, name: str) -> dict[str, Any]:
        db = self._need_db()
        return {"id": db.create_collection(name), "name": name}

    def rename_collection(self, collection_id: int, name: str) -> bool:
        return self._need_db().rename_collection(collection_id, name)

    def delete_collection(self, collection_id: int) -> bool:
        return self._need_db().delete_collection(collection_id)

    def set_favorite(self, card: dict[str, Any], value: bool) -> None:
        self._need_db().set_favorite(card["path"], card["hash"], value)

    def set_card_collections(self, card: dict[str, Any], ids: list[int]) -> None:
        self._need_db().set_card_collections(card["path"], card["hash"], ids)

    # ---- 扫描 ----
    def scan(self) -> ScanResult:
        self._need_db()
        with self._scan_lock:
            return self.scanner.scan()  # type: ignore[union-attr]

    def refresh_file(self, path: str | Path) -> ScanResult:
        """保存卡之后立即刷新该文件的索引（无需等 watcher）。"""
        self._need_db()
        with self._scan_lock:
            return self.scanner.scan_file(canon(path).as_posix())  # type: ignore[union-attr]

    def clear_index(self) -> int:
        """清空扫描出来的数据：卡索引、缩略图、封面色缓存。来源列表和评分保留，卡文件一个不碰。"""
        db = self._need_db()
        with self._scan_lock:
            n = db.clear_index()
            self.thumbs.clear()
            if self.colors_dir.is_dir():
                for p in self.colors_dir.glob("*.txt"):
                    p.unlink(missing_ok=True)
        return n

    # ---- 查询 ----
    def list_cards(
        self, category: str | None = None, *, page: int = 1, page_size: int = 50,
        sort: str = "name", order: str = "asc",
    ) -> Page:
        return self._need_db().list_cards(
            category, page=page, page_size=page_size, sort=sort, order=order
        )

    def search(
        self, query: str, *, category: str | None = None, page: int = 1, page_size: int = 50,
    ) -> Page:
        return self._need_db().search(query, category=category, page=page, page_size=page_size)

    def get_card(self, card_id: int) -> dict[str, Any] | None:
        return self._need_db().get_card(card_id)

    def get_card_by_path(self, path: str | Path) -> dict[str, Any] | None:
        return self._need_db().get_by_path(canon(path).as_posix())

    def abs_path(self, path: str | Path) -> Path:
        """卡文件的真实路径。必须落在某个来源里；文件夹来源下的符号链接/目录联接若指到来源外，也拒绝。"""
        key = canon(path).as_posix()
        loc = self._locate(key)
        if loc is None:
            raise ValueError(f"path is not in any source: {path}")
        p = Path(key)
        src = next(s for s in self.sources if s.path == loc.source)
        if src.is_dir and not p.resolve().is_relative_to(Path(src.path).resolve()):
            raise ValueError(f"path escapes source: {path}")
        return p

    # ---- 冲突 / 保存 ----
    def check_conflict(
        self, path: str | Path, expected_mtime_ns: int, expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> ConflictResult:
        return check_conflict(self.abs_path(path), expected_mtime_ns, expected_hash, expected_size)

    def save_card_bytes(
        self, path: str | Path, data: bytes, *, expected_mtime_ns: int | None = None,
        expected_hash: str | None = None,
    ) -> None:
        """安全保存：冲突检查 -> 原子写 -> 刷新索引。直接写回源文件，不做备份。冲突时抛 ConflictError。"""
        target = self.abs_path(path)
        if expected_mtime_ns is not None and target.exists():
            c = self.check_conflict(path, expected_mtime_ns, expected_hash)
            if c.conflict:
                raise ConflictError(str(path), c)
        atomic_write(target, data)
        self.refresh_file(path)

    # ---- 缩略图 ----
    def get_thumbnail(self, card_id: int) -> Path | None:
        card = self.get_card(card_id)
        if card is None or card["is_broken"]:
            return None
        data = self.image_reader(self.abs_path(card["path"]))
        if not data:
            return None
        return self.thumbs.get(card["hash"], data)

    # ---- 监听 ----
    def start_watching(self, on_change: Callable[[LibraryChanges], None] | None = None) -> None:
        self._need_db()
        if self._watching:
            return
        self._on_change = on_change
        self._watching = True
        self._rewatch()

    def stop_watching(self) -> None:
        self._watching = False
        w, self._watcher = self._watcher, None
        if w is not None:
            w.stop()

    def _rewatch(self) -> None:
        """来源变了就按新来源重建监听。只有调用过 start_watching 之后才会监听。"""
        if not self._watching:
            return
        old, self._watcher = self._watcher, None
        if old is not None:
            old.stop()
        w = Watcher(
            [Path(s.path) for s in self.sources if s.is_dir],
            [Path(s.path) for s in self.sources if not s.is_dir],
            self._handle_events,
            lambda p, is_dir: self._locate(canon(p).as_posix(), is_dir) is not None,
            self.debounce,
        )
        w.start()
        self._watcher = w

    def _handle_events(self, events: list[ChangeEvent]) -> None:
        changes = LibraryChanges()
        need_full = False
        with self._scan_lock:
            for ev in events:
                for p in (ev.src, ev.dest):
                    if p is None:
                        continue
                    key = canon(p).as_posix()
                    if ev.is_dir:
                        need_full = True
                    elif is_card_file(p.name):
                        r = self.scanner.scan_file(key)  # type: ignore[union-attr]
                        if r.removed:
                            changes.removed.append(key)
                        elif r.added or r.updated:
                            changes.upserted.append(key)
            if need_full:
                changes.full_rescan = self.scanner.scan()  # type: ignore[union-attr]
        if self._on_change and (changes.upserted or changes.removed or changes.full_rescan):
            self._on_change(changes)


def covers_same(a: Source, b: Source) -> bool:
    return same_path(a.path, b.path)


def covers_same(a: Source, b: Source) -> bool:
    return same_path(a.path, b.path)


class ConflictError(Exception):
    def __init__(self, path: str, result: ConflictResult):
        super().__init__(f"{path} was modified externally ({result.reason})")
        self.path = path
        self.result = result
