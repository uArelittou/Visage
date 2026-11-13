import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
for p in (str(ROOT), str(Path(__file__).parent), str(TESTS / "rating")):
    if p not in sys.path:
        sys.path.insert(0, p)

from api_helpers import Env, FakeClient, build_library, make_client  # noqa: E402
from rating_helpers import Sample  # noqa: E402

from backend.api import create_app  # noqa: E402


@pytest.fixture(scope="session")
def mk():
    path = TESTS / "fixtures" / "cards" / "make_cards.py"
    spec = importlib.util.spec_from_file_location("make_cards_api", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """接口层默认读写用户配置目录；测试一律指到临时目录，并清掉评分环境变量。"""
    monkeypatch.setenv("QIANMIANLU_HOME", str(tmp_path / "home"))
    for name in ("BASE_URL", "API_KEY", "MODEL", "TIMEOUT", "TEMPERATURE", "MAX_TOKENS",
                 "MAX_RETRIES", "CONTEXT_CHAR_BUDGET"):
        monkeypatch.delenv("QIANMIANLU_RATING_" + name, raising=False)


@pytest.fixture
def env(tmp_path, mk):
    root = tmp_path / "cards"
    build_library(root, mk)
    outside = tmp_path / "secret.png"
    outside.write_bytes(mk.plain_png())
    config = tmp_path / "home" / "config.json"
    fake = FakeClient()
    app = create_app(config_path=config, rating_client=fake, watch_debounce=0.1, restore_library=False)
    with make_client(app) as client:
        app.state.qml.open_library()
        r = client.post("/api/sources", json={"path": str(root)})
        assert r.status_code == 201, r.text
        yield Env(client, root, config, fake, outside, mk)


@pytest.fixture
def bare_client(tmp_path):
    """尚未设置卡库、没有注入假模型的应用。"""
    config = tmp_path / "home" / "config.json"
    app = create_app(config_path=config, watch_debounce=0.1, restore_library=False)
    with make_client(app) as client:
        yield client, config


@pytest.fixture(scope="session")
def lin() -> Sample:
    return Sample("linxiaoye")
