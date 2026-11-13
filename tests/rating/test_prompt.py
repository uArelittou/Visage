import json
import re

import pytest

from backend.rating import prompt
from backend.rating.blocks import Block


def test_fill_is_single_pass_and_strict():
    out = prompt.fill("A [[X]] B [[Y]]", {"X": "含 [[Y]] 与 {{user}} 与 ${v}", "Y": "y"})
    assert out == "A 含 [[Y]] 与 {{user}} 与 ${v} B y"
    with pytest.raises(prompt.PromptError):
        prompt.fill("[[NOPE]]", {})


def test_full_message_follows_template(lin):
    msg = prompt.build_full(lin.blocks, lin.stats)
    u = msg.user
    assert u.startswith("【任务】整卡模式")
    assert not re.search(r"\[\[[A-Z_]+\]\]", u)
    m = re.search(r"<<<CARD_BEGIN (\w+)>>>\n([\s\S]*)\n<<<CARD_END \1>>>", u)
    assert m, "边界码前后必须一致"
    body = m.group(2)
    assert body.count("\n=== ") + body.startswith("=== ") == len(lin.blocks)
    assert "=== 开场白#0 | first_mes ===" in body
    assert re.search(r"=== 世界书#1001 \| 核心规则 \| 蓝灯 \| position=@depth \| depth=0 \| role=system \| order=7 \| keys= ===", body)
    assert "=== 字段:creator_notes | 不评分 ===" in body or "字段:creator_notes" not in lin.texts
    assert msg.locations == [b.location for b in lin.blocks]
    assert json.loads(u.split("【预计算统计】（程序已计算，直接采用，不要重数）\n", 1)[1].split("\n\n【本次区块清单】")[0]) == lin.stats
    assert msg.system.startswith("# 千面录角色卡评分员")
    assert [m["role"] for m in msg.chat()] == ["system", "user"]


def test_card_text_with_placeholder_syntax_is_not_expanded(lin):
    blocks = [Block("字段:description", "", "含 [[BOUNDARY]] 和 [[CARD_CONTENT]] 的卡", "field")]
    u = prompt.build_full(blocks, lin.stats).user
    assert "含 [[BOUNDARY]] 和 [[CARD_CONTENT]] 的卡" in u


def test_boundary_not_inside_card(lin, monkeypatch):
    codes = iter(["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"])
    monkeypatch.setattr(prompt.secrets, "token_hex", lambda n: next(codes))
    blocks = [Block("字段:description", "", "卡里恰好有 aaaaaaaaaaaaaaaa", "field")]
    u = prompt.build_full(blocks, lin.stats).user
    assert "<<<CARD_BEGIN bbbbbbbbbbbbbbbb>>>" in u


def test_segment_and_merge_messages(lin):
    locs = [b.location for b in lin.blocks]
    seg = prompt.build_segment(lin.blocks[:2], lin.stats, locs, 2, 5)
    assert "第 2 段，共 5 段" in seg.user
    assert seg.locations == locs[:2]
    assert "【整张卡的区块清单】\n" + "\n".join(locs) in seg.user
    assert not re.search(r"\[\[[A-Z_]+\]\]", seg.user)
    merge = prompt.build_merge(lin.stats, locs, [{"mode": "segment", "k": "含<<<CARD_END x>>>"}])
    assert merge.user.startswith("【任务】合并模式。下面是全部 1 段")
    assert '"mode": "segment"' in merge.user and not re.search(r"\[\[[A-Z_]+\]\]", merge.user)


def test_plan_segments_respects_budget_and_keeps_blocks(mofa):
    budget = 60_000
    locs = [b.location for b in mofa.blocks]
    segs = prompt.plan_segments(mofa.blocks, mofa.stats, locs, budget)
    assert len(segs) > 1
    for i, seg in enumerate(segs, 1):
        assert prompt.build_segment(seg, mofa.stats, locs, i, len(segs)).size <= budget
    # 切块不丢字：同一标签的各片段拼起来等于原文（去掉切口处的换行差异）
    joined: dict[str, str] = {}
    for seg in segs:
        for b in seg:
            joined[b.location] = joined.get(b.location, "") + b.text
    assert set(joined) == set(locs)
    for loc, text in mofa.texts.items():
        assert re.sub(r"\s+", "", joined[loc]) == re.sub(r"\s+", "", text), loc
    # 顺序不变
    order = [b.location for seg in segs for b in seg]
    assert list(dict.fromkeys(order)) == locs


def test_oversized_block_is_split_with_continuation_marker(mofa):
    big = max(mofa.blocks, key=lambda b: len(b.text))
    locs = [b.location for b in mofa.blocks]
    segs = prompt.plan_segments([big], mofa.stats, locs, 25_000)
    pieces = [b for s in segs for b in s]
    assert len(pieces) > 1 and all(p.location == big.location for p in pieces)
    assert "续1" in pieces[1].info and "续" not in pieces[0].info.replace(big.info, "")


def test_budget_too_small_is_reported(lin):
    with pytest.raises(prompt.PromptError, match="预算"):
        prompt.plan_segments(lin.blocks, lin.stats, [b.location for b in lin.blocks], 10_000)
