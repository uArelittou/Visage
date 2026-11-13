import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.library import Library  # noqa: E402
from library_helpers import FakeLoader  # noqa: E402


@pytest.fixture
def loader():
    return FakeLoader()


@pytest.fixture
def root(tmp_path):
    """用户的卡文件夹（一个来源）。"""
    r = tmp_path / "cards"
    r.mkdir()
    return r


@pytest.fixture
def lib(tmp_path, loader):
    """数据目录在 tmp_path/data，和卡文件夹分开；调用 lib.open([root]) 指定来源。"""
    library = Library(tmp_path / "data", loader, debounce=0.15)
    yield library
    library.close()
