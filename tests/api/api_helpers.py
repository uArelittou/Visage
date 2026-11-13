import json
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from backend.rating.llm import ChatResult

API_KEY = "sk-API-TEST-SECRET-0123456789abcdef"


class FakeClient:
    """假评分模型：handler(messages, n) 返回 dict/str，或直接抛异常。"""

    model = "fake-model"

    def __init__(self, handler=None):
        self.handler = handler or (lambda messages, n: "{}")
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        out = self.handler(messages, self.calls)
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return ChatResult(text=text, finish_reason="stop", model=self.model)


@dataclass
class Env:
    client: TestClient
    root: Path
    config: Path
    fake: FakeClient
    outside: Path  # 卡库外一张真实存在的图片，路径穿越测试用
    mk: object

    def path(self, rel: str) -> str:
        """卡库根目录下的相对路径 -> 索引里的卡路径（绝对路径，正斜杠）。"""
        return (self.root / rel).as_posix()

    def card(self, rel: str) -> dict:
        """按相对路径取列表里的那一行。"""
        r = self.client.get("/api/cards", params={"page_size": 500})
        for item in r.json()["items"]:
            if item["path"] == self.path(rel):
                return item
        raise AssertionError(f"索引里没有 {rel}")

    def card_id(self, rel: str) -> int:
        return self.card(rel)["id"]


def build_library(root: Path, mk) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hero.png").write_bytes(mk.card_png(mk.V2_CARD))
    (root / "webcard.webp").write_bytes(mk.webp_card(mk.V2_CARD))
    (root / "bad.png").write_bytes(mk.SIG + bytes(range(7, 200)))
    sub = root / "sub"
    sub.mkdir()
    (sub / "second.json").write_text(json.dumps(mk.V3_CARD, ensure_ascii=False), encoding="utf-8")
    deep = sub / "deep"
    deep.mkdir()
    (deep / "third.png").write_bytes(mk.card_png(mk.V3_CARD, keyword="ccv3", seed=9))


def make_client(app) -> TestClient:
    # Host 校验只认回环地址，TestClient 默认的 testserver 会被拒
    return TestClient(app, base_url="http://127.0.0.1")


def wait_until(cond, timeout=10.0, interval=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(interval)
    raise AssertionError("等待超时")
