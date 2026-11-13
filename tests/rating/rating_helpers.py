import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from backend.card import Card, load_card
from backend.rating.blocks import card_blocks
from backend.rating.stats import compute_stats

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rating"


def make_card(**data) -> Card:
    return Card.from_dict({"spec": "chara_card_v3", "spec_version": "3.0", "data": data})


def lore(uid, content="内容内容", *, enabled=True, constant=False, keys=(), name="条目", order=100, position=0):
    return {
        "id": uid, "comment": name, "content": content, "enabled": enabled, "constant": constant,
        "keys": list(keys), "secondary_keys": [], "insertion_order": order,
        "extensions": {"position": position, "depth": 4, "role": 0},
    }


class Sample:
    """一张真卡 + 它的区块、统计和一份合格的模型输出。"""

    def __init__(self, name: str):
        self.name = name
        self.path = FIXTURES / f"{name}.card.json"
        if not self.path.exists():
            # 第三方作者的卡不随仓库发布（见 .gitignore），克隆后缺样本时跳过依赖它的测试
            import pytest

            pytest.skip(f"缺少评分样本卡 {self.path.name}", allow_module_level=False)
        self.card = load_card(self.path)
        self.blocks = card_blocks(self.card)
        self.stats = compute_stats(self.card, self.blocks)
        self.texts = {b.location: b.text for b in self.blocks}
        self._output = json.loads((FIXTURES / f"{name}.output.json").read_text(encoding="utf-8"))

    @property
    def output(self) -> dict:
        return copy.deepcopy(self._output)


class FakeServer:
    def __init__(self, responses):
        self.responses = list(responses)  # (status, body_bytes | callable(headers, body) -> bytes)
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
                status, payload = outer.responses.pop(0) if outer.responses else (500, b"{}")
                if callable(payload):
                    payload = payload(self.headers, body)
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"


def ok_body(text="你好", **extra):
    return json.dumps({
        "model": "m-1", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 3}, **extra,
    }).encode()
