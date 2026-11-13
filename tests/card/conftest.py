from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "cards"


@pytest.fixture(scope="session")
def mk():
    """样例卡生成器模块（tests/fixtures/cards/make_cards.py）。"""
    spec = importlib.util.spec_from_file_location("make_cards", _FIXTURE_DIR / "make_cards.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def cards(mk) -> dict[str, Path]:
    """把全部样例卡生成到 tests/fixtures/cards/，返回 文件名 -> 路径。只读使用。"""
    return mk.make_all(_FIXTURE_DIR)


@pytest.fixture
def work(cards, tmp_path):
    """按文件名把样例复制到临时目录并返回副本路径；写测试一律用副本。"""
    def _copy(name: str) -> Path:
        dst = tmp_path / name
        shutil.copy(cards[name], dst)
        return dst
    return _copy
