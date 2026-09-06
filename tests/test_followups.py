"""P5 follow-up paradox — dropout table, calls-to-close distribution, explicit recommendation rules.

The synthetic frame engineers stage 4 (follow-up 3 → follow-up 4) to be anomalous: almost nobody
drops there while every other follow-up stage loses about a fifth of the remaining leads.
"""

import pandas as pd
import pytest

from ml.data import clean, load_raw
from ml.followups import (
    CUT_THRESHOLD,
    EXTEND_THRESHOLD,
    closed_deals_followups,
    dropout_table,
    followup_insights,
    recommendation,
    render_report_md,
)

STAGES = ["leads_answered", "followup_1", "followup_2", "followup_3", "followup_4", "followup_5", "closed"]


def _frame(calls_to_closed: list[int], funnel=(100, 80, 64, 51, 50, 40, 10)) -> pd.DataFrame:
    """One row per entry in calls_to_closed; funnel counts identical per row, budgets cycle over the tiers."""
    budgets = [500, 3000, 8000]
    rows = []
    for i, calls in enumerate(calls_to_closed):
        leads = 200
        counts = dict(zip(STAGES, funnel, strict=True))
        rows.append(
            {
                "ad_budget": budgets[i % 3],
                "num_leads": leads,
                "leads_not_answered": leads - counts["leads_answered"],
                **counts,
                "not_closed": counts["followup_5"] - counts["closed"],
                "calls_to_closed": calls,
                "calls_to_not_closed": 4,
                "customer_acquisition_cost": 1000,
                "ltv_months": 40 - 4 * calls,
                "purchased": 1,
                "upsell": 1 if calls <= 3 else 0,
                "cumulative_profit": 20000 - 2000 * calls,
                "referred": calls <= 2,
            }
        )
    return pd.DataFrame(rows)


def test_dropout_table_has_six_stages_with_rates_in_unit_interval():
    d = dropout_table(_frame([2, 3, 4]))
    assert [s["stage"] for s in d["stages"]] == [
        "answered → follow-up 1",
        "follow-up 1 → follow-up 2",
        "follow-up 2 → follow-up 3",
        "follow-up 3 → follow-up 4",
        "follow-up 4 → follow-up 5",
        "follow-up 5 → closed",
    ]
    assert all(0 <= s["dropout_rate"] <= 1 for s in d["stages"])
    assert d["stages"][0]["dropout_rate"] == pytest.approx(0.2)  # 100 → 80
    assert d["stages"][3]["dropout_rate"] == pytest.approx(1 - 50 / 51, abs=1e-4)  # rates are rounded to 4 dp
    assert d["stages"][-1]["is_close"] and not d["stages"][0]["is_close"]
    assert d["remaining"][0]["column"] == "num_leads" and d["remaining"][-1]["column"] == "closed"


def test_dropout_by_tier_covers_the_tiers_present():
    d = dropout_table(_frame([2, 3, 4]))
    assert set(d["stages"][0]["dropout_rate_by_tier"]) == {"Low", "Mid", "High"}
    assert dropout_table(_frame([2]))["stages"][0]["dropout_rate_by_tier"].keys() == {"Low"}


def test_unexpected_stage_is_the_engineered_one():
    ins = followup_insights(_frame([2, 3, 4, 5]))
    r = ins["recommendation"]
    assert r["unexpected_stage"] == "follow-up 3 → follow-up 4"
    assert r["unexpected_dropout"] < r["median_other_dropout"]
    assert "lower" in r["unexpected_note"]


def test_close_stage_is_never_nominated_as_unexpected():
    # closing loses 75% of follow-up-5 leads (largest drop by far) but it is a close rate, not a dropout
    r = followup_insights(_frame([2, 3], funnel=(100, 80, 64, 51, 41, 33, 8)))["recommendation"]
    assert r["unexpected_stage"] != "follow-up 5 → closed"


def test_closed_deals_distribution():
    c = closed_deals_followups(_frame([1, 2, 2, 3, 3, 3, 4, 5, 6, 7]))
    assert c["closed"]["n"] == 10 and c["closed"]["median"] == 3
    assert c["closed"]["share_gt_3"] == pytest.approx(0.4) and c["closed"]["share_gt_5"] == pytest.approx(0.2)
    assert c["closed"]["distribution"]["3"] == 3
    assert c["not_closed"]["median"] == 4
    assert [v["calls"] for v in c["value_by_calls"]] == ["1–2", "3", "4–5", "6+"]
    assert c["value_by_calls"][0]["mean_ltv_months"] > c["value_by_calls"][-1]["mean_ltv_months"]


def test_recommendation_cut_when_few_deals_need_more_than_three_calls():
    r = followup_insights(_frame([1, 2, 2, 3, 3, 3, 3, 2, 1, 4]))["recommendation"]  # 10% > 3
    assert r["share_closed_gt_3"] < CUT_THRESHOLD and r["verdict"] == "cut_after_3" and r["reason"]


def test_recommendation_keep_when_many_deals_need_more_than_three_calls():
    r = followup_insights(_frame([2, 3, 4, 5, 4, 3, 2, 5]))["recommendation"]  # 50% > 3, none > 5
    assert r["verdict"] == "keep" and "more than 3 calls" in r["reason"]
    assert r["cut_threshold"] == CUT_THRESHOLD and r["extend_threshold"] == EXTEND_THRESHOLD
    assert r["value_note"]


def test_recommendation_extend_when_many_deals_need_more_than_five_calls():
    r = followup_insights(_frame([6, 7, 6, 8, 2, 3, 4, 5]))["recommendation"]  # 50% > 5
    assert r["verdict"] == "extend"


def test_recommendation_survives_empty_frame_gracefully():
    d = dropout_table(_frame([1]))
    c = {"closed": {"n": 0}, "not_closed": {"n": 0}, "value_by_calls": []}  # no closed deals at all
    r = recommendation(d, c)
    assert r["verdict"] == "keep" and r["reason"]


def test_real_data_smoke_and_report_block():
    ins = followup_insights(clean(load_raw()))
    assert len(ins["dropout"]["stages"]) == 6
    assert ins["recommendation"]["verdict"] in {"keep", "cut_after_3", "extend"}
    assert ins["recommendation"]["reason"] and ins["recommendation"]["unexpected_stage"]
    md = render_report_md(ins)
    assert md.startswith("## P5") and "unexpectedly" in md and "Recommendation" in md
