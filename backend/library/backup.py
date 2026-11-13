"""保存前备份、从备份恢复、外部修改冲突检测，以及原子写。"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 旧版把备份放在卡文件夹里的 .kabao 下。保存流程已不再备份，BackupManager 只作为独立工具保留。
DATA_DIR_NAME = ".kabao"
DEFAULT_KEEP = 10


def atomic_write(path: Path, data: bytes) -> None:
    """临时文件 + fsync + os.replace。临时文件以 .tmp 结尾，watcher 会忽略它。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class BackupInfo:
    rel_path: str
    name: str  # 备份文件名，如 20261109-102626-123456.png
    path: Path
    size: int
    created: float  # 取自文件名里的时间戳，而非 mtime


@dataclass(frozen=True)
class ConflictResult:
    conflict: bool
    reason: str  # "" / "missing" / "modified"
    current_mtime_ns: int | None = None
    current_size: int | None = None
    current_hash: str | None = None


def check_conflict(
    path: Path,
    expected_mtime_ns: int,
    expected_hash: str | None = None,
    expected_size: int | None = None,
) -> ConflictResult:
    """调用方在读取卡时记下 mtime_ns/hash，保存前传入。磁盘值不同即视为被外部改过。
    mtime 变了但内容 hash 仍相同（如仅 touch）不算冲突。"""
    try:
        st = path.stat()
    except OSError:
        return ConflictResult(True, "missing")
    if st.st_mtime_ns == expected_mtime_ns and (
        expected_size is None or st.st_size == expected_size
    ):
        return ConflictResult(False, "", st.st_mtime_ns, st.st_size, expected_hash)
    cur_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_hash is not None and cur_hash == expected_hash:
        return ConflictResult(False, "", st.st_mtime_ns, st.st_size, cur_hash)
    return ConflictResult(True, "modified", st.st_mtime_ns, st.st_size, cur_hash)


class BackupManager:
    def __init__(self, root: Path, keep: int = DEFAULT_KEEP):
        self.root = Path(root)
        self.keep = max(1, keep)
        self.backup_root = self.root / DATA_DIR_NAME / "backups"

    # ---- 路径 ----
    def _card_path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise ValueError(f"path escapes library root: {rel}")
        return self.root / rel

    def _backup_dir(self, rel: str) -> Path:
        self._card_path(rel)
        return self.backup_root / Path(rel)

    # ---- 备份 ----
    def backup(self, rel: str) -> BackupInfo | None:
        """备份当前磁盘上的文件；文件不存在（新建卡）返回 None。"""
        src = self._card_path(rel)
        if not src.is_file():
            return None
        d = self._backup_dir(rel)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = d / f"{stamp}{src.suffix}"
        n = 0
        while dest.exists():  # 同一微秒内重复调用
            n += 1
            dest = d / f"{stamp}-{n}{src.suffix}"
        shutil.copy2(src, dest)
        self._prune(d)
        return self._info(rel, dest)

    def _prune(self, d: Path) -> None:
        files = sorted(p for p in d.iterdir() if p.is_file())
        for old in files[: max(0, len(files) - self.keep)]:
            old.unlink(missing_ok=True)

    @staticmethod
    def _parse_ts(name: str) -> float:
        try:
            return datetime.strptime(name[:22], "%Y%m%d-%H%M%S-%f").timestamp()
        except ValueError:
            return 0.0

    def _info(self, rel: str, p: Path) -> BackupInfo:
        return BackupInfo(rel, p.name, p, p.stat().st_size, self._parse_ts(p.name))

    def list_backups(self, rel: str) -> list[BackupInfo]:
        """最新的在前。"""
        d = self._backup_dir(rel)
        if not d.is_dir():
            return []
        files = sorted((p for p in d.iterdir() if p.is_file()), reverse=True)
        return [self._info(rel, p) for p in files]

    # ---- 恢复 ----
    def restore(self, rel: str, backup_name: str, *, backup_current: bool = True) -> BackupInfo | None:
        """把备份写回原路径（原子替换）。默认先把当前文件也备份一份，使恢复可撤销。
        返回恢复前对当前文件做的备份（若有）。"""
        if Path(backup_name).name != backup_name:
            raise ValueError("invalid backup name")
        src = self._backup_dir(rel) / backup_name
        if not src.is_file():
            raise FileNotFoundError(f"backup not found: {rel} / {backup_name}")
        data = src.read_bytes()  # 先读入内存：prune 可能删掉它
        pre = self.backup(rel) if backup_current else None
        atomic_write(self._card_path(rel), data)
        return pre

    # ---- 冲突检测 ----
    def check_conflict(
        self,
        rel: str,
        expected_mtime_ns: int,
        expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> ConflictResult:
        return check_conflict(self._card_path(rel), expected_mtime_ns, expected_hash, expected_size)
