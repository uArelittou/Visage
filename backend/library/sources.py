"""来源：用户收录的文件夹或单张卡文件。路径规范化、包含关系、去重与合并。

卡库不复制任何文件，只在来源的原路径上建索引。数据库里的卡路径（cards.path）是规范化后的
绝对路径（正斜杠），既是卡的唯一键，也是评分的键。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .scanner import is_card_file



class SourceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AlreadyInLibrary(SourceError):
    def __init__(self, source: "Source"):
        super().__init__("already_in_library", "已在卡库里")
        self.source = source


@dataclass(frozen=True)
class Source:
    path: str  # 规范化绝对路径，正斜杠
    is_dir: bool

    @property
    def name(self) -> str:
        p = Path(self.path)
        return p.name or p.as_posix()  # 盘符根目录没有 name


@dataclass(frozen=True)
class Location:
    """一个文件在某个来源里的位置。sub 是来源文件夹内的子路径（正斜杠），单卡来源恒为空。"""

    source: str
    sub: str


def canon(path: str | os.PathLike[str]) -> Path:
    """只做词法规范化，不解析符号链接：来源路径要和 watchdog 事件、os.walk 给出的字符串前缀一致。"""
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _nc(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def same_path(a: str, b: str) -> bool:
    return _nc(a) == _nc(b)


def _inside_parts(child: str, parent: str) -> tuple[str, ...] | None:
    """child 在 parent 之下时返回相对路径的各段（相同则为空元组），否则 None。Windows 下不分大小写。"""
    c, p = _nc(child), _nc(parent)
    if c == p:
        return ()
    prefix = p if p.endswith(os.sep) else p + os.sep
    if not c.startswith(prefix):
        return None
    return tuple(x for x in c[len(prefix):].split(os.sep) if x)


def is_inside(child: str, parent: str) -> bool:
    return _inside_parts(child, parent) is not None


def covers(src: Source, path: str, is_dir: bool) -> bool:
    """扫描 src 时会不会收进 path。以「.」开头的文件夹整个跳过，所以它们底下的东西不算被覆盖。"""
    if not src.is_dir:
        return not is_dir and same_path(src.path, path)
    parts = _inside_parts(path, src.path)
    if parts is None:
        return False
    dir_parts = parts if is_dir else parts[:-1]
    return not any(x.startswith(".") for x in dir_parts)


def make_source(path: str | os.PathLike[str]) -> Source:
    """从配置里读回来源。路径可能暂时不存在（移动硬盘没插），此时按扩展名猜是文件还是文件夹。"""
    p = canon(path)
    if p.exists():
        is_dir = p.is_dir()
    else:
        is_dir = not is_card_file(p.name)
    return Source(p.as_posix(), is_dir)


def plan_add(existing: list[Source], path: str | os.PathLike[str]) -> tuple[Source, list[Source]]:
    """返回 (新来源, 被它合并掉的旧来源)。已被现有来源覆盖时抛 AlreadyInLibrary。"""
    p = canon(path)
    if not p.exists():
        raise SourceError("path_not_found", "路径不存在")
    is_dir = p.is_dir()
    if not is_dir and not is_card_file(p.name):
        raise SourceError("bad_ext", "只能收录文件夹，或 PNG、WebP、JSON 卡")
    key = p.as_posix()
    for s in existing:
        if covers(s, key, is_dir):
            raise AlreadyInLibrary(s)
    new = Source(key, is_dir)
    merged = [s for s in existing if new.is_dir and covers(new, s.path, s.is_dir)]
    return new, merged


def locate(sources: list[Source], path: str, is_dir: bool = False) -> Location | None:
    for s in sources:
        if not covers(s, path, is_dir):
            continue
        if not s.is_dir:
            return Location(s.path, "")
        folder = path if is_dir else os.path.dirname(path)
        sub = os.path.relpath(folder, s.path).replace(os.sep, "/")
        return Location(s.path, "" if sub == "." else sub)
    return None
