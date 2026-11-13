"""接口层的运行时状态：当前卡库、评分服务、后台评分任务、变更通知。

只做编排，不重写 backend.library / backend.rating 里的逻辑。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.card import load_card
from backend.card.fsio import atomic_write_bytes
from backend.library import (
    AddResult, AlreadyInLibrary, Library, LibraryChanges, ScanResult, Source, SourceError,
)
from backend.rating.llm import ChatClient, LLMError
from backend.rating.service import RatingError, RatingFailed, RatingService
from backend.rating.settings import RatingSettings, load_settings, save_settings, settings_path

log = logging.getLogger(__name__)

LIBRARY_SECTION = "library"
MAX_SCAN_ERRORS = 20


class ApiProblem(Exception):
    """路由层转成 HTTP 响应的业务错误。extra 会并入 detail。"""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


# ---------------------------------------------------------------- 变更通知
class ChangeFeed:
    """进程内的版本号 + 最近若干条变更。前端带上次的 version 来取增量，可选长轮询。"""

    def __init__(self, maxlen: int = 200):
        self._cond = threading.Condition()
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.version = 0

    def push(self, kind: str, **data: Any) -> int:
        with self._cond:
            self.version += 1
            self._items.append({"version": self.version, "kind": kind, "time": time.time(), **data})
            self._cond.notify_all()
            return self.version

    def since(self, since: int, wait: float = 0.0) -> dict[str, Any]:
        with self._cond:
            if wait > 0 and self.version <= since:
                self._cond.wait_for(lambda: self.version > since, timeout=wait)
            items = [i for i in self._items if i["version"] > since]
            # 前端落后太多（缓冲已被挤掉）或服务重启过：增量不可信，要求整体刷新
            lost = since > self.version or (
                self.version > since and (not items or items[0]["version"] > since + 1)
            )
            return {"version": self.version, "reset": lost, "changes": items}


# ---------------------------------------------------------------- 后台评分
@dataclass
class RatingJob:
    card_id: int
    state: str = "running"  # running / done / failed
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    error_type: str | None = None
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id, "state": self.state, "started_at": self.started_at,
            "finished_at": self.finished_at, "error": self.error, "error_type": self.error_type,
            "error_details": self.error_details,
        }


def scan_to_dict(res: ScanResult) -> dict[str, Any]:
    return {
        "added": res.added, "updated": res.updated, "skipped": res.skipped,
        "removed": res.removed, "broken": res.broken, "duration": round(res.duration, 4),
        "errors": [{"path": p, "message": m} for p, m in res.errors[:MAX_SCAN_ERRORS]],
    }


class AppState:
    def __init__(
        self,
        *,
        config_path: Path | None = None,
        rating_client: ChatClient | None = None,
        debounce: float = 0.5,
        loader: Callable[[Path], Any] = load_card,
    ):
        self.config_path = Path(config_path) if config_path else settings_path()
        # 索引库、缩略图、封面色缓存和来源列表同放一个目录，不写进用户的卡文件夹
        self.data_dir = self.config_path.parent
        self.rating_client = rating_client
        self.debounce = debounce
        self.loader = loader
        self.feed = ChangeFeed()
        self.lib: Library | None = None
        self.rating: RatingService | None = None
        self.last_scan: dict[str, Any] | None = None
        self.opening = False
        self.open_error: str | None = None
        self.write_lock = threading.Lock()  # 保存卡：冲突检查到写盘之间不能被另一次保存插入
        self._swap_lock = threading.RLock()
        self._config_lock = threading.Lock()
        self._jobs: dict[int, RatingJob] = {}
        self._jobs_lock = threading.Lock()

    # ------------------------------------------------------------ 配置文件
    def _read_config(self) -> dict[str, Any]:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}
        return data if isinstance(data, dict) else {}

    def configured_sources(self) -> list[str]:
        try:
            with self._config_lock:
                section = self._read_config().get(LIBRARY_SECTION)
        except (OSError, ValueError):
            return []
        if not isinstance(section, dict):
            return []
        sources = section.get("sources")
        if isinstance(sources, list):
            return [s for s in sources if isinstance(s, str) and s]
        # 旧版只记一个卡库根目录：当作一个文件夹来源沿用
        root = section.get("root")
        return [root] if isinstance(root, str) and root else []

    def _persist_sources(self) -> None:
        lib = self.lib
        if lib is None:
            return
        try:
            with self._config_lock:
                data = self._read_config()
                section = data.get(LIBRARY_SECTION)
                section = dict(section) if isinstance(section, dict) else {}
                section.pop("root", None)
                section["sources"] = [s.path for s in lib.sources]
                data[LIBRARY_SECTION] = section
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(
                    self.config_path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                )
        except (OSError, ValueError):
            # 配置文件读不了就不覆盖，避免冲掉里面的评分 API 配置
            log.warning("无法保存来源列表到配置文件，下次启动需要重新添加")

    # ------------------------------------------------------------ 评分设置
    def rating_settings(self) -> RatingSettings:
        return load_settings(self.config_path)

    def update_rating_settings(self, updates: dict[str, Any]) -> RatingSettings:
        with self._config_lock:
            save_settings(updates, path=self.config_path)
        return self.rating_settings()

    # ------------------------------------------------------------ 卡库
    def need_lib(self) -> Library:
        lib = self.lib
        if lib is None:
            raise ApiProblem(409, "no_library", "卡库正在打开" if self.opening else "卡库尚未打开")
        return lib

    def need_rating(self) -> RatingService:
        svc = self.rating
        if svc is None:
            raise ApiProblem(409, "no_library", "卡库尚未打开")
        return svc

    def open_library(self) -> dict[str, Any]:
        """按配置里的来源建库并扫描。没有来源也照常打开，首页为空。"""
        new = Library(self.data_dir, self.loader, debounce=self.debounce)
        res = new.open(self.configured_sources())
        with self._swap_lock:
            old, self.lib = self.lib, new
            self.rating = RatingService(
                new, settings_provider=self.rating_settings, client=self.rating_client
            )
            self.last_scan = scan_to_dict(res)
            self.open_error = None
            with self._jobs_lock:
                self._jobs.clear()
        if old is not None:
            old.close()
        new.start_watching(self._on_watch)
        self.feed.push("library_opened", sources=len(new.sources))
        return self.last_scan

    def restore_library_async(self) -> None:
        """启动时打开卡库。扫描可能很久，放后台，不拖慢窗口出现。"""
        self.opening = True

        def run() -> None:
            try:
                self.open_library()
            except Exception as e:  # noqa: BLE001
                log.exception("open library failed")
                self.open_error = f"打开卡库失败: {type(e).__name__}"
            finally:
                self.opening = False

        threading.Thread(target=run, name="library-restore", daemon=True).start()

    def add_source(self, path: str) -> AddResult:
        lib = self.need_lib()
        try:
            res = lib.add_source(path)
        except AlreadyInLibrary as e:
            raise ApiProblem(409, e.code, e.message, source=e.source.path) from None
        except SourceError as e:
            status = 422 if e.code == "not_a_card" else 400
            raise ApiProblem(status, e.code, e.message) from None
        self._persist_sources()
        self.last_scan = scan_to_dict(res.scan)
        self.feed.push("sources", added=res.source.path, merged=[s.path for s in res.merged])
        return res

    def remove_source(self, path: str) -> Source:
        lib = self.need_lib()
        removed = lib.remove_source(path)
        if removed is None:
            raise ApiProblem(404, "source_not_found", "来源列表里没有这一项")
        self._persist_sources()
        self.feed.push("sources", removed=removed.path)
        return removed

    def replace_file_source(self, old: str, new: str) -> None:
        lib = self.need_lib()
        if any(s.path == old and not s.is_dir for s in lib.sources):
            lib.replace_file_source(old, new)
            self._persist_sources()

    def clear_library(self) -> int:
        n = self.need_lib().clear_index()
        self.last_scan = None
        self.feed.push("cleared", cards=n)
        return n

    def rescan(self) -> dict[str, Any]:
        lib = self.need_lib()
        res = lib.scan()
        self.last_scan = scan_to_dict(res)
        self.feed.push("rescan", **{k: self.last_scan[k] for k in ("added", "updated", "removed")})
        return self.last_scan

    def close(self) -> None:
        with self._swap_lock:
            lib, self.lib, self.rating = self.lib, None, None
        if lib is not None:
            lib.close()

    def _on_watch(self, changes: LibraryChanges) -> None:
        self.feed.push(
            "watch", upserted=changes.upserted, removed=changes.removed,
            full_rescan=changes.full_rescan is not None,
        )

    # ------------------------------------------------------------ 后台评分
    def start_rating(self, card_id: int) -> RatingJob:
        svc = self.need_rating()
        lib = self.need_lib()
        if lib.get_card(card_id) is None:
            raise ApiProblem(404, "card_not_found", f"没有 id={card_id} 的卡")
        settings = self.rating_settings()
        if self.rating_client is None and not settings.configured:
            raise ApiProblem(
                400, "rating_not_configured", "评分 API 未配置完整，缺少: " + ", ".join(settings.missing())
            )
        secret = settings.api_key
        with self._jobs_lock:
            cur = self._jobs.get(card_id)
            if cur is not None and cur.state == "running":
                raise ApiProblem(409, "rating_busy", "这张卡正在评分", job=cur.to_dict())
            job = RatingJob(card_id)
            self._jobs[card_id] = job

        def run() -> None:
            try:
                svc.rate_card(card_id)
                job.state = "done"
            except RatingFailed as e:
                self._fail(job, e, secret, details=e.errors[:5])
            except (RatingError, LLMError) as e:
                self._fail(job, e, secret)
            except Exception as e:  # noqa: BLE001  未知异常只给类型名，避免把请求内容/密钥带出去
                log.exception("rating job crashed")
                job.state, job.error_type = "failed", type(e).__name__
                job.error = f"评分过程出错: {type(e).__name__}"
            finally:
                job.finished_at = time.time()
                self.feed.push("rating", card_id=card_id, state=job.state)

        threading.Thread(target=run, name=f"rating-{card_id}", daemon=True).start()
        return job

    @staticmethod
    def _fail(job: RatingJob, e: Exception, secret: str, details: list[str] | None = None) -> None:
        def clean(s: str) -> str:
            return s.replace(secret, "***") if secret else s

        job.state = "failed"
        job.error_type = type(e).__name__
        job.error = clean(str(e))
        job.error_details = [clean(d) for d in (details or [])]

    def rating_job(self, card_id: int) -> RatingJob | None:
        with self._jobs_lock:
            return self._jobs.get(card_id)
