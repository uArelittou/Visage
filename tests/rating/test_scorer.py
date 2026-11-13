import pytest

from backend.rating.scorer import ScoreError, round_total, score_final


def test_mofa_lenient_sample_scores_8_9(mofa):
    r = score_final(mofa.output, mofa.stats)
    assert r["total"] == 8.9
    assert r["bonus"]["total"] == 0.8 and r["bonus"]["sum"] == pytest.approx(0.8)
    assert r["deductions"]["total"] == pytest.approx(0.2)
    assert r["opening"]["score"] == 6.0
    assert r["dimensions"]["opening"]["score"] == 6.0
    assert r["dimensions"]["character"]["weight"] == 19


def test_linxiaoye_sample_scores_8_0(lin):
    r = score_final(lin.output, lin.stats)
    assert r["total"] == 8.0
    assert r["base"] == pytest.approx(8.014)
    assert r["opening"]["count_score"] == 3
    assert r["opening"]["length_avg"] == 2.0
    assert [g["index"] for g in r["opening"]["greetings"]] == [0, 1, 2, 3, 4]


def test_not_applicable_weights_are_redistributed(lin):
    out = lin.output
    for k in ("character", "world", "scene", "lorebook_structure", "player_space", "lorebook_placement"):
        out["dimensions"][k]["score"] = 6
    out["bonus"] = {k: {"score": 0, "evidence": [], "reason": ""} for k in ("mvu", "frontend", "style")}
    out["deductions"] = []
    # opening 与 guidance 之外全是 6 分
    base_full = score_final(out, lin.stats)["base"]
    out["dimensions"]["guidance"] = {"applicable": False, "reason": "无"}
    out["not_applicable"] = ["guidance"]
    r = score_final(out, lin.stats)
    assert not r["dimensions"]["guidance"]["applicable"]
    weights = {k: v["weight"] for k, v in r["dimensions"].items() if v["applicable"]}
    assert sum(weights.values()) == 93
    expect = (6 * (93 - 8) + r["opening"]["score"] * 8) / 93
    assert r["base"] == pytest.approx(expect, abs=1e-4)
    assert base_full != r["base"]


def test_all_not_applicable_gives_zero_base(lin):
    out = lin.output
    for k, d in out["dimensions"].items():
        out["dimensions"][k] = {"applicable": False, "reason": "无"}
    out["not_applicable"] = list(out["dimensions"])
    stats = dict(lin.stats, program_not_applicable=["lorebook_structure", "lorebook_placement", "opening"])
    r = score_final(out, stats)
    assert r["base"] == 0
    assert r["total"] == round_total(r["bonus"]["total"] - r["deductions"]["total"])


def test_program_na_overrides_model_scores(lin):
    stats = dict(lin.stats, program_not_applicable=["lorebook_placement"])
    r = score_final(lin.output, stats)
    assert r["dimensions"]["lorebook_placement"]["applicable"] is False
    assert r["dimensions"]["lorebook_placement"]["score"] is None


def _q(loc="世界书#1001"):
    return {"quote": "引用原文", "location": loc}


def test_deduction_caps(lin):
    out = lin.output
    out["bonus"] = {k: {"score": 0, "evidence": [], "reason": ""} for k in ("mvu", "frontend", "style")}
    # 同类型三个重度 = 1.8，先封顶到 0.6
    out["deductions"] = [{"type": "duplication", "severity": "heavy", "quotes": [_q()], "reason": "x"}] * 3
    r = score_final(out, lin.stats)
    assert r["deductions"]["by_type"]["duplication"] == {"raw": pytest.approx(1.8), "capped": 0.6}
    assert r["deductions"]["total"] == pytest.approx(0.6)
    # 四个类型各 0.6 = 2.4，再封顶到 1.5
    types = ("duplication", "contradiction", "irrelevant", "nonsense")
    out["deductions"] = [{"type": t, "severity": "heavy", "quotes": [_q()], "reason": "x"} for t in types]
    r = score_final(out, lin.stats)
    assert r["deductions"]["sum_before_cap"] == pytest.approx(2.4)
    assert r["deductions"]["total"] == 1.5


def test_bonus_cap_and_clamp(lin):
    out = lin.output
    out["bonus"] = {
        "mvu": {"score": 0.3, "evidence": [], "reason": ""},
        "frontend": {"score": 0.3, "evidence": [], "reason": ""},
        "style": {"score": 0.2, "evidence": [], "reason": ""},
    }
    out["deductions"] = []
    for k, d in out["dimensions"].items():
        if k != "opening":
            d["score"] = 10
    for g in out["dimensions"]["opening"]["greetings"]:
        g["guidance"], g["freedom"] = 3, 2
    r = score_final(out, lin.stats)
    assert r["total"] == 10.0 and r["total_raw"] > 10 - 1e-9


def test_rounding_is_half_up_and_clamped():
    assert round_total(8.25) == 8.3
    assert round_total(8.05) == 8.1
    assert round_total(8.349999) == 8.3
    assert round_total(-0.4) == 0.0
    assert round_total(11) == 10.0


def test_missing_greeting_judgement_is_error(lin):
    out = lin.output
    out["dimensions"]["opening"]["greetings"].pop()
    with pytest.raises(ScoreError):
        score_final(out, lin.stats)


def test_bailianling_sample_scores_7_7(bai):
    r = score_final(bai.output, bai.stats)
    assert r["total"] == 7.7
    assert r["opening"]["count_score"] == 2
    assert r["deductions"]["total"] == pytest.approx(0.7)
    assert r["review"].startswith("主人")


def test_fv125_sample_scores_7_4(fv):
    r = score_final(fv.output, fv.stats)
    assert r["total"] == 7.4
    assert r["bonus"]["total"] == pytest.approx(0.7)
    assert r["opening"]["count_score"] == 0
