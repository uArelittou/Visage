"""按 rubric.json 算总分。模型只给单项分和判定，总分一律在这里算。"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .rubric import load_rubric, tier_score

# 这几项是否适用由程序按统计决定，模型的判断与之冲突时以程序为准
PROGRAM_DECIDED_NA = ("lorebook_structure", "lorebook_placement", "opening")


class ScoreError(ValueError):
    pass


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def _q1(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round_total(x: Decimal | float) -> float:
    """截断到 [0,10] 后四舍五入到一位小数。"""
    v = max(Decimal(0), min(Decimal(10), _d(x)))
    return float(_q1(v))


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def opening_score(
    greetings: list[dict[str, Any]], stats: dict[str, Any], rubric: dict[str, Any]
) -> dict[str, Any]:
    op = rubric["opening"]
    lengths = {g["index"]: g for g in stats["greeting_lengths"]}
    by_index = {g["index"]: g for g in greetings}
    missing = sorted(set(lengths) - set(by_index))
    if missing:
        raise ScoreError(f"开场白判定缺少 index {missing}")
    rows = []
    for idx in sorted(lengths):
        g = by_index[idx]
        rows.append({
            "index": idx,
            "chars": lengths[idx]["chars"],
            "length_score": lengths[idx]["length_score"],
            "guidance": g["guidance"],
            "freedom": g["freedom"],
        })
    count_score = _d(tier_score(op["count_score"], stats["greeting_count"]))
    len_avg = _mean([_d(r["length_score"]) for r in rows])
    gui_avg = _mean([_d(r["guidance"]) for r in rows])
    fre_avg = _mean([_d(r["freedom"]) for r in rows])
    raw = count_score + len_avg + gui_avg + fre_avg
    score = max(_d(op["min_total"]), min(_d(op["max_total"]), raw))
    return {
        "count_score": float(count_score),
        "length_avg": float(len_avg),
        "guidance_avg": float(gui_avg),
        "freedom_avg": float(fre_avg),
        "raw": float(raw),
        "score": float(score),
        "greetings": rows,
    }


def score_final(
    output: dict[str, Any], stats: dict[str, Any], rubric: dict[str, Any] | None = None
) -> dict[str, Any]:
    """output 是通过校验的 mode=final 输出；返回可直接入库的评分明细。"""
    rubric = rubric or load_rubric()
    dims_cfg = {d["id"]: d for d in rubric["dimensions"]}
    na_by_program = set(stats.get("program_not_applicable", []))
    model_dims = output["dimensions"]

    dimensions: dict[str, dict[str, Any]] = {}
    opening_detail: dict[str, Any] | None = None
    for dim_id, cfg in dims_cfg.items():
        md = model_dims[dim_id]
        if dim_id in na_by_program:
            dimensions[dim_id] = {
                "name": cfg["name"], "weight": cfg["weight"], "applicable": False, "score": None,
                "reason": "卡内没有可评内容（由程序判定）", "evidence": [],
            }
            continue
        if not md.get("applicable"):
            dimensions[dim_id] = {
                "name": cfg["name"], "weight": cfg["weight"], "applicable": False, "score": None,
                "reason": md.get("reason", ""), "evidence": [],
            }
            continue
        if dim_id == "opening":
            opening_detail = opening_score(md["greetings"], stats, rubric)
            dimensions[dim_id] = {
                "name": cfg["name"], "weight": cfg["weight"], "applicable": True,
                "score": opening_detail["score"], "reason": "", "evidence": [],
            }
        else:
            dimensions[dim_id] = {
                "name": cfg["name"], "weight": cfg["weight"], "applicable": True,
                "score": md["score"], "reason": md.get("reason", ""), "evidence": md.get("evidence", []),
            }

    applicable = {k: v for k, v in dimensions.items() if v["applicable"]}
    wsum = sum(_d(v["weight"]) for v in applicable.values())
    base = (
        sum((_d(v["score"]) * _d(v["weight"]) for v in applicable.values()), Decimal(0)) / wsum
        if wsum else Decimal(0)
    )

    bonus_items = {}
    bonus_sum = Decimal(0)
    for bid, b in output["bonus"].items():
        bonus_items[bid] = {
            "score": b["score"], "evidence": b.get("evidence", []), "reason": b.get("reason", ""),
        }
        bonus_sum += _d(b["score"])
    bonus_total = min(bonus_sum, _d(rubric["bonus"]["cap"]))

    ded_cfg = rubric["deductions"]
    items = []
    by_type: dict[str, Decimal] = {}
    for d in output["deductions"]:
        pen = _d(ded_cfg["severity"][d["severity"]])
        by_type[d["type"]] = by_type.get(d["type"], Decimal(0)) + pen
        items.append({
            "type": d["type"], "severity": d["severity"], "penalty": float(pen),
            "quotes": d["quotes"], "reason": d.get("reason", ""),
        })
    per_cap = _d(ded_cfg["per_type_cap"])
    capped = {t: min(v, per_cap) for t, v in by_type.items()}
    ded_before_cap = sum(capped.values(), Decimal(0))
    ded_total = min(ded_before_cap, _d(ded_cfg["cap"]))

    total_raw = base + bonus_total - ded_total
    return {
        "card_type": output.get("card_type", ""),
        "dimensions": dimensions,
        "opening": opening_detail,
        "base": float(round(base, 4)),
        "bonus": {"items": bonus_items, "sum": float(bonus_sum), "total": float(bonus_total)},
        "deductions": {
            "items": items,
            "by_type": {
                t: {"raw": float(by_type[t]), "capped": float(capped[t])} for t in by_type
            },
            "sum_before_cap": float(ded_before_cap),
            "total": float(ded_total),
        },
        "total_raw": float(round(total_raw, 4)),
        "total": round_total(total_raw),
        "injection_notes": output.get("injection_notes", []),
        "review": output.get("review", ""),
    }
