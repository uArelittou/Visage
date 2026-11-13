"""评分全流程：读卡 -> 统计 -> 拼消息 -> 调模型（必要时分段+合并）-> 校验 -> 算分 -> 入库。

函数都以 card_id 为入参、返回可直接 JSON 化的 dict，接口层只需转发。
显示分 = 用户总分（若有）否则 AI 总分；重新 AI 评分不动用户总分；卡改过后旧分照常显示。
"""
from __future__ import annotations

import json
import math
import threading
from typing import Any, Callable

from . import prompt as prompts
from .blocks import card_blocks
from .llm import ChatClient, ChatResult, LLMError, OpenAIChatClient
from .rubric import load_rubric
from .scorer import round_total, score_final
from .settings import RatingSettings, load_settings
from .stats import compute_stats
from .validate import (
    MAX_REPORTED_ERRORS, OutputError, QuoteIndex, ValidationResult, parse_json_text,
    validate_final, validate_segment,
)


class RatingError(Exception):
    pass


class CardNotFoundError(RatingError):
    pass


class RatingConfigError(RatingError):
    """评分 API 没配好。消息只列缺哪些字段，不含取值。"""


class RatingBusyError(RatingError):
    pass


class RatingFailed(RatingError):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = list(errors or [])


_OVERFLOW_HINTS = ("context", "token", "too long", "too large", "maximum", "length", "上下文", "超长")


def _is_context_overflow(e: LLMError) -> bool:
    # 各家 OpenAI 兼容接口报超长的状态码和措辞不统一，只能按 400/413 + 关键词粗判
    if e.status not in (400, 413):
        return False
    text = str(e).lower()
    return any(h in text for h in _OVERFLOW_HINTS)


def _feedback(errors: list[str]) -> str:
    shown = errors[:MAX_REPORTED_ERRORS]
    lines = "\n".join(f"- {e}" for e in shown)
    more = f"\n（另有 {len(errors) - len(shown)} 条问题未列出）" if len(errors) > len(shown) else ""
    return (
        "你上一次的输出没有通过程序校验，问题如下：\n"
        f"{lines}{more}\n"
        "请逐条修正后重新输出完整的 JSON。只输出 JSON，不要代码围栏或解释；"
        "引用原句必须逐字取自卡内容，location 照抄区块标签。"
    )


def default_client_factory(s: RatingSettings) -> ChatClient:
    return OpenAIChatClient(
        s.base_url, s.api_key, s.model, timeout=s.timeout,
        temperature=s.temperature, max_tokens=s.max_tokens,
    )


class RatingService:
    def __init__(
        self,
        library: Any,
        *,
        settings_provider: Callable[[], RatingSettings] = load_settings,
        client: ChatClient | None = None,
        client_factory: Callable[[RatingSettings], ChatClient] = default_client_factory,
    ):
        self.library = library
        self._settings_provider = settings_provider
        self._client = client
        self._client_factory = client_factory
        self._busy: set[str] = set()
        self._busy_lock = threading.Lock()

    # ------------------------------------------------------------ 读
    def _db(self):
        db = self.library.db
        if db is None:
            raise RuntimeError("Library is not open")
        return db

    def _card_row(self, card_id: int) -> dict[str, Any]:
        row = self.library.get_card(card_id)
        if row is None:
            raise CardNotFoundError(f"没有 id={card_id} 的卡")
        return row

    def get_rating(self, card_id: int) -> dict[str, Any]:
        row = self._card_row(card_id)
        r = self._db().get_rating_row(row["path"])
        ai_total = r["ai_total"] if r else None
        user_total = r["user_total"] if r else None
        return {
            "card_id": card_id,
            "path": row["path"],
            "display_score": user_total if user_total is not None else ai_total,
            "ai_total": ai_total,
            "user_total": user_total,
            "user_rated_at": r["user_rated_at"] if r else None,
            "has_ai": bool(r and r["ai_result"]),
            "model": (r["model"] or None) if r else None,
            "rubric_version": r["rubric_version"] if r else None,
            "rated_at": r["rated_at"] if r else None,
            "result": json.loads(r["ai_result"]) if r and r["ai_result"] else None,
        }

    # ------------------------------------------------------------ 用户总分
    def set_user_total(self, card_id: int, total: float) -> dict[str, Any]:
        if isinstance(total, bool) or not isinstance(total, (int, float)) or math.isnan(total):
            raise ValueError("总分必须是数字")
        if not 0 <= total <= 10:
            raise ValueError("总分必须在 0~10 之间")
        row = self._card_row(card_id)
        self._db().set_user_total(row["path"], row["hash"], round_total(total))
        return self.get_rating(card_id)

    def clear_user_total(self, card_id: int) -> dict[str, Any]:
        row = self._card_row(card_id)
        self._db().clear_user_total(row["path"])
        return self.get_rating(card_id)

    # ------------------------------------------------------------ AI 评分
    def _make_client(self, settings: RatingSettings) -> ChatClient:
        if self._client is not None:
            return self._client
        missing = settings.missing()
        if missing:
            raise RatingConfigError("评分 API 未配置完整，缺少: " + ", ".join(missing))
        return self._client_factory(settings)

    def _ask(
        self,
        client: ChatClient,
        message: prompts.Message,
        validate: Callable[[Any], ValidationResult],
        max_retries: int,
    ) -> dict[str, Any]:
        messages = message.chat()
        errors: list[str] = []
        for _ in range(max_retries + 1):
            reply: ChatResult = client.complete(messages)
            truncated = reply.finish_reason == "length"
            if truncated:
                errors = ["输出被长度上限截断，JSON 不完整。请缩短 reason 和 evidence 后重新输出"]
            else:
                try:
                    res = validate(parse_json_text(reply.text))
                    errors = res.errors
                except OutputError as e:
                    errors = e.errors
                if not errors:
                    assert res.output is not None
                    return res.output
            if reply.text and not truncated:
                messages = [*messages, {"role": "assistant", "content": reply.text}]
            messages = [*messages, {"role": "user", "content": _feedback(errors)}]
        raise RatingFailed(
            f"模型输出连续 {max_retries + 1} 次未通过校验：" + "；".join(errors[:3]), errors
        )

    def rate_card(self, card_id: int) -> dict[str, Any]:
        row = self._card_row(card_id)
        if row["is_broken"]:
            raise RatingError(f"卡文件无法解析，不能评分: {row['error']}")
        settings = self._settings_provider()
        client = self._make_client(settings)
        path = row["path"]
        with self._busy_lock:
            if path in self._busy:
                raise RatingBusyError("这张卡正在评分")
            self._busy.add(path)
        try:
            result = self._run(row, settings, client)
            rubric = load_rubric()
            # 全部成功后才写库，失败不留半成品
            self._db().save_ai_rating(
                path, row["hash"], ai_total=result["total"],
                ai_result=json.dumps(result, ensure_ascii=False),
                model=client.model, rubric_version=rubric["version"],
            )
        finally:
            with self._busy_lock:
                self._busy.discard(path)
        return self.get_rating(card_id)

    def _run(self, row: dict[str, Any], settings: RatingSettings, client: ChatClient) -> dict[str, Any]:
        card = self.library.loader(self.library.abs_path(row["path"]))
        blocks = card_blocks(card)
        stats = compute_stats(card, blocks)
        all_locations = [b.location for b in blocks]
        full_texts = {b.location: b.text for b in blocks}
        whole_card = QuoteIndex(full_texts)

        def final_validator(obj: Any) -> ValidationResult:
            return validate_final(obj, stats=stats, quotes=whole_card)

        full = prompts.build_full(blocks, stats)
        meta: dict[str, Any]
        budget = settings.context_char_budget
        output = None
        if full.size <= budget:
            try:
                output = self._ask(client, full, final_validator, settings.max_retries)
                meta = {"mode": "full", "segments": 1}
            except LLMError as e:
                if not _is_context_overflow(e):
                    raise
                # 配置的预算比模型实际上下文大，退到分段；按整卡的一半切，至少分两段
                budget = max(full.size // 2, 1)
        if output is None:
            try:
                segments = prompts.plan_segments(blocks, stats, all_locations, budget)
            except prompts.PromptError as e:
                raise RatingConfigError(str(e)) from None
            total = len(segments)
            seg_outputs = []
            for i, seg_blocks in enumerate(segments, start=1):
                msg = prompts.build_segment(seg_blocks, stats, all_locations, i, total)
                seg_index = QuoteIndex({loc: full_texts[loc] for loc in msg.locations})

                def seg_validator(obj: Any, _i=i, _idx=seg_index, _msg=msg) -> ValidationResult:
                    return validate_segment(
                        obj, stats=stats, quotes=_idx, index=_i, total=total,
                        segment_locations=_msg.locations)

                seg_outputs.append(self._ask(client, msg, seg_validator, settings.max_retries))
            merge = prompts.build_merge(stats, all_locations, seg_outputs)
            output = self._ask(client, merge, final_validator, settings.max_retries)
            meta = {"mode": "segmented", "segments": total}
        result = score_final(output, stats)
        result["meta"] = meta
        return result
