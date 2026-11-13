"""watchdog 监听来源，事件去抖后批量回调。"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .scanner import is_temp_name

log = logging.getLogger(__name__)

_KINDS = {"created", "modified", "deleted", "moved"}


@dataclass(frozen=True)
class ChangeEvent:
    kind: str  # created / modified / deleted / moved
    src: Path
    is_dir: bool = False
    dest: Path | None = None  # 仅 moved


class Watcher:
    """同一路径在 debounce 窗口内的多次事件合并为最后一次；窗口安静后一次性回调整批。

    folders 递归监听；files（单卡来源）只能监听所在文件夹，所以用 accept 过滤掉同目录的其他文件。
    accept(path, is_dir) 由 Library 提供，判断这条路径是否属于某个来源。"""

    def __init__(
        self,
        folders: list[Path],
        files: list[Path],
        callback: Callable[[list[ChangeEvent]], None],
        accept: Callable[[Path, bool], bool],
        debounce: float = 0.5,
    ):
        self.folders = list(folders)
        self.files = list(files)
        self.callback = callback
        self.accept = accept
        self.debounce = debounce
        self._observer: Observer | None = None
        self._lock = threading.Lock()
        self._pending: dict[Path, ChangeEvent] = {}
        self._timer: threading.Timer | None = None

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._observer is not None:
            return
        handler = _Handler(self)
        obs = Observer()
        for folder in self.folders:
            self._schedule(obs, handler, folder, recursive=True)
        for parent in {f.parent for f in self.files}:
            self._schedule(obs, handler, parent, recursive=False)
        obs.start()
        self._observer = obs

    @staticmethod
    def _schedule(obs: Observer, handler: FileSystemEventHandler, path: Path, *, recursive: bool) -> None:
        try:
            if not path.is_dir():
                raise FileNotFoundError(path)
            obs.schedule(handler, str(path), recursive=recursive)
        except OSError:
            # 来源暂时不存在（移动硬盘没插）：跳过，不能因此让整个监听起不来
            log.warning("无法监听 %s", path)

    def stop(self) -> None:
        obs, self._observer = self._observer, None
        if obs is not None:
            obs.stop()
            obs.join(timeout=5)
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()

    @property
    def running(self) -> bool:
        return self._observer is not None

    # ---- 过滤与去抖 ----
    def _ignored(self, p: Path, is_dir: bool) -> bool:
        return is_temp_name(p.name) or not self.accept(p, is_dir)

    def _push(self, ev: ChangeEvent) -> None:
        # moved 事件：源或目标任一是正常路径就要处理
        paths = [ev.src] + ([ev.dest] if ev.dest else [])
        if all(self._ignored(p, ev.is_dir) for p in paths):
            return
        with self._lock:
            self._pending[ev.src] = ev
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            events = list(self._pending.values())
            self._pending.clear()
            self._timer = None
        if not events:
            return
        try:
            self.callback(events)
        except Exception:  # noqa: BLE001
            log.exception("watcher callback failed")


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: Watcher):
        self._w = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        kind = event.event_type
        if kind not in _KINDS:
            return
        # 目录的 modified 只是子项变动的副作用，没有信息量
        if event.is_directory and kind == "modified":
            return
        dest = getattr(event, "dest_path", "") or None
        self._w._push(
            ChangeEvent(
                kind=kind,
                src=Path(str(event.src_path)),
                is_dir=bool(event.is_directory),
                dest=Path(str(dest)) if dest else None,
            )
        )
