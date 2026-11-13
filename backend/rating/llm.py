"""OpenAI 兼容 Chat Completions 客户端，只用标准库。

密钥只出现在请求头里。所有异常消息都经过 _redact，且不带请求 URL 的查询串，
避免服务端回显或代理日志把密钥带进异常、日志或数据库。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

USER_AGENT = "qianmianlu-rating/1.0"
_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class ChatResult:
    text: str
    finish_reason: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class ChatClient(Protocol):
    """评分流程只依赖这个接口，测试里用假客户端替换。"""

    model: str

    def complete(self, messages: list[dict[str, str]]) -> ChatResult: ...


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def chat_completions_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


class OpenAIChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 300.0,
        temperature: float | None = 0.2,
        max_tokens: int | None = None,
        transient_retries: int = 2,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not base_url or not model:
            raise ValueError("base_url 和 model 不能为空")
        self._url = chat_completions_url(base_url)
        self._api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.transient_retries = max(0, transient_retries)
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"OpenAIChatClient(host={urlsplit(self._url).netloc!r}, model={self.model!r})"

    def _host(self) -> str:
        return urlsplit(self._url).netloc

    def _payload(self, messages: list[dict[str, str]]) -> bytes:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _once(self, data: bytes) -> ChatResult:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(self._url, data=data, headers=headers, method="POST")
        try:
            with self._open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001  读错误体失败不应掩盖 HTTP 状态
                detail = ""
            msg = f"{self._host()} 返回 HTTP {e.code}"
            if detail:
                msg += f": {_redact(detail, self._api_key)}"
            raise LLMError(msg, status=e.code, retryable=e.code in _RETRY_STATUS) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise LLMError(
                _redact(f"连接 {self._host()} 失败: {type(reason).__name__}: {reason}", self._api_key),
                retryable=True,
            ) from None
        return self._parse(raw)

    def _parse(self, raw: bytes) -> ChatResult:
        try:
            obj = json.loads(raw.decode("utf-8"))
            choice = obj["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError(f"{self._host()} 返回的内容不是 Chat Completions 格式") from None
        if isinstance(content, list):  # 部分网关把内容拆成 [{type:text,text:...}]
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str):
            raise LLMError(f"{self._host()} 返回的 message.content 不是文本")
        return ChatResult(
            text=content,
            finish_reason=str(choice.get("finish_reason") or ""),
            model=str(obj.get("model") or self.model),
            usage=obj.get("usage") if isinstance(obj.get("usage"), dict) else {},
        )

    def complete(self, messages: list[dict[str, str]]) -> ChatResult:
        data = self._payload(messages)
        attempt = 0
        while True:
            try:
                return self._once(data)
            except LLMError as e:
                if not e.retryable or attempt >= self.transient_retries:
                    raise
                attempt += 1
                self._sleep(2.0 * attempt)
