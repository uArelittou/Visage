"""递归扫描来源（文件夹或单张卡），增量写入 Database。"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .db import CardRecord, Database

if TYPE_CHECKING:
    from .sources import Location, Source

CARD_EXTS = frozenset({".png", ".webp", ".json"})
_TEMP_SUFFIXES = (".tmp", ".temp", ".part", ".crdownload", "~")

Loader = Callable[[Path], Any]


def is_card_file(name: str) -> bool:
    return Path(name).suffix.lower() in CARD_EXTS and not is_temp_name(name)


def is_temp_name(name: str) -> bool:
    low = name.lower()
    return low.endswith(_TEMP_SUFFIXES) or low.startswith(("~$", ".~"))


def posix(p: str) -> str:
    return p.replace(os.sep, "/") if os.sep != "/" else p


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    broken: int = 0  # 本次解析失败的数量
    errors: list[tuple[str, str]] = field(default_factory=list)
    duration: float = 0.0


def _count(obj: Any) -> int:
    return len(obj) if obj else 0


def _lorebook_entries(book: Any) -> int:
    if not isinstance(book, dict):
        return 0
    entries = book.get("entries")
    return len(entries) if isinstance(entries, (list, dict)) else 0


def card_to_record(path: str, st: os.stat_result, digest: str, card: Any, loc: "Location") -> CardRecord:
    greetings = [card.first_mes] if getattr(card, "first_mes", "") else []
    greetings += [g for g in (getattr(card, "alternate_greetings", None) or []) if g]
    return CardRecord(
        path=path,
        source=loc.source,
        sub=loc.sub,
        mtime_ns=st.st_mtime_ns,
        size=st.st_size,
        hash=digest,
        name=getattr(card, "name", "") or Path(path).stem,
        creator=getattr(card, "creator", "") or "",
        tags=list(getattr(card, "tags", None) or []),
        description=getattr(card, "description", "") or "",
        greeting_count=len(greetings),
        lorebook_count=_lorebook_entries(getattr(card, "character_book", None)),
        regex_count=_count(getattr(card, "regex_scripts", None)),
        script_count=_count(getattr(card, "scripts", None)),
        spec=getattr(card, "spec", "") or "",
        search_greetings="\n".join(greetings),
    )


class Scanner:
    """sources 与 locate 由 Library 注入：来源列表会变，Scanner 每次扫描时重新取。
    data_dir 是千面录自己的数据目录，万一落在某个来源文件夹里，里面的缩略图（.webp）和 config.json 不能当成卡。"""

    def __init__(
        self,
        db: Database,
        loader: Loader,
        sources: Callable[[], "list[Source]"],
        locate: Callable[[str], "Location | None"],
        data_dir: Path,
    ):
        self.db = db
        self.loader = loader
        self.sources = sources
        self.locate = locate
        self._data_norm = os.path.normcase(os.path.abspath(data_dir))

    def _skip_dir(self, parent: str, name: str) -> bool:
        if name.startswith("."):
            return True
        return os.path.normcase(os.path.abspath(os.path.join(parent, name))) == self._data_norm

    def _walk(self, src: "Source") -> dict[str, tuple[os.stat_result, "Location"]]:
        from .sources import Location  # sources 反过来依赖本模块的文件名规则，只能延迟导入

        found: dict[str, tuple[os.stat_result, Location]] = {}
        if not src.is_dir:
            if is_card_file(Path(src.path).name):
                try:
                    found[src.path] = (os.stat(src.path), Location(src.path, ""))
                except OSError:
                    pass
            return found
        for dirpath, dirnames, filenames in os.walk(src.path):
            dirnames[:] = [d for d in dirnames if not self._skip_dir(dirpath, d)]
            here = posix(dirpath)
            sub = os.path.relpath(dirpath, src.path)
            loc = Location(src.path, "" if sub == "." else posix(sub))
            for fn in filenames:
                if not is_card_file(fn):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    found[f"{here}/{fn}"] = (os.stat(full), loc)
                except OSError:
                    continue
        return found

    def scan(self, only: "list[Source] | None" = None) -> ScanResult:
        """only=None：扫描全部来源，并清掉不属于任何来源的旧记录。
        给定 only：只处理这些来源，其余来源的记录原样保留。"""
        t0 = time.perf_counter()
        res = ScanResult()
        targets = self.sources() if only is None else only
        files: dict[str, tuple[os.stat_result, "Location"]] = {}
        for s in targets:
            files.update(self._walk(s))
        known = self.db.snapshot()
        scoped = set(known) if only is None else {
            p for p, v in known.items() if v[3] in {s.path for s in targets}
        }
        with self.db.transaction():
            for path, (st, loc) in files.items():
                old = known.get(path)
                if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
                    if old[3] != loc.source:
                        self.db.set_location(path, loc.source, loc.sub)
                    res.skipped += 1
                    continue
                self._index_file(path, st, loc, old, res)
            res.removed = self.db.remove_many([p for p in scoped if p not in files])
            self.db.relink_ratings()
        res.duration = time.perf_counter() - t0
        return res

    def scan_file(self, path: str) -> ScanResult:
        """单文件刷新（watcher / 保存后调用）。文件不存在或不再属于任何来源则从索引移除。"""
        res = ScanResult()
        loc = self.locate(path)
        try:
            st = os.stat(path)
        except OSError:
            st = None
        if st is None or loc is None:
            res.removed = self.db.remove_many([path])
            self.db.relink_ratings()
            return res
        old = self._old_stat(path)
        if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
            if old[3] != loc.source:
                self.db.set_location(path, loc.source, loc.sub)
            res.skipped = 1
            return res
        self._index_file(path, st, loc, old, res)
        self.db.relink_ratings()
        return res

    def _old_stat(self, path: str) -> tuple[int, int, str, str] | None:
        row = self.db.get_by_path(path)
        return (row["mtime_ns"], row["size"], row["hash"], row["source"]) if row else None

    def _index_file(
        self, path: str, st: os.stat_result, loc: "Location",
        old: tuple[int, int, str, str] | None, res: ScanResult,
    ) -> None:
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as e:
            res.errors.append((path, str(e)))
            return
        digest = file_hash(data)
        if old and old[2] == digest:
            self.db.touch_stat(path, st.st_mtime_ns, st.st_size)
            if old[3] != loc.source:
                self.db.set_location(path, loc.source, loc.sub)
            res.skipped += 1
            return
        try:
            card = self.loader(p)
            rec = card_to_record(path, st, digest, card, loc)
        except Exception as e:  # noqa: BLE001  坏卡不能中断扫描
            msg = f"{type(e).__name__}: {e}"
            rec = CardRecord(
                path=path, source=loc.source, sub=loc.sub,
                mtime_ns=st.st_mtime_ns, size=st.st_size, hash=digest,
                name=p.stem, is_broken=True, error=msg,
            )
            res.broken += 1
            res.errors.append((path, msg))
        self.db.upsert(rec)
        if old:
            res.updated += 1
        else:
            res.added += 1
