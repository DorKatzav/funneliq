import numpy as np
import pandas as pd
import pytest

from ml.data import RAW_COLUMNS, clean, load_raw
from ml.eda import overview_stats, render_findings_md


def _synthetic_raw() -> pd.DataFrame:
    """20 rows with known answers: two budgets per tier, hand-built funnel counts."""
    rows = []
    budgets = [500, 1500, 2000, 5000, 6000, 20000]
    rng = np.random.default_rng(0)
    for i in range(20):
        b = budgets[i % len(budgets)]
        leads = {500: 10, 1500: 20, 2000: 30, 5000: 50, 6000: 60, 20000: 100}[b]
        answered = leads // 2
        f1, f2, f3, f4, f5 = answered, answered - 2, answered - 4, answered - 5, answered - 6
        closed = {500: 1, 1500: 1, 2000: 4, 5000: 6, 6000: 3, 20000: 5}[b]
        purchased = 0 if i in (3, 9) else 1
        rows.append(
            {
                "ad_budget": b,
                "num_leads": leads,
                "leads_answered": answered,
                "leads_not_answered": leads - answered,
                "followup_1": f1,
                "followup_2": f2,
                "followup_3": f3,
                "followup_4": f4,
                "followup_5": f5,
                "not_closed": f5 - closed,
                "closed": closed,
                "calls_to_closed": 3,
                "calls_to_not_closed": 4,
                "customer_acquisition_cost": b // max(closed, 1),
                "ltv_months": float(rng.integers(1, 40)) if i != 5 else np.nan,
                "purchased": purchased,
                "upsell": 0 if purchased == 0 else int(i % 2),
                "cumulative_profit": 0.0 if purchased == 0 else float(1000 * closed) if i != 7 else np.nan,
                "referred": "Yes" if i % 3 == 0 else "No",
            }
        )
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


@pytest.fixture(scope="module")
def stats() -> dict:
    return overview_stats(clean(_synthetic_raw()))


def test_counts_and_missing(stats):
    c = stats["counts"]
    assert c["rows"] == 20 and c["customers"] == 18 and c["non_customers"] == 2
    assert c["incomplete_rows"] == 2
    assert c["missing_per_column"] == {"ltv_months": 1, "cumulative_profit": 1}


def test_tiers_are_ordered_and_best_tier_is_mid(stats):
    tiers = [t["tier"] for t in stats["conversion_by_tier"]]
    assert tiers == ["Low", "Mid", "High"]
    conv = {t["tier"]: t["conversion"] for t in stats["conversion_by_tier"]}
    # Low: (1+1)/(10+20)=0.0667 ; Mid: (4+6)/(30+50)=0.125 ; High: (3+5)/(60+100)=0.05
    assert conv["Low"] == pytest.approx(2 / 30, abs=1e-4)
    assert conv["Mid"] == pytest.approx(10 / 80, abs=1e-4)
    assert conv["High"] == pytest.approx(8 / 160, abs=1e-4)
    assert stats["best_tier"] == "Mid"


def test_budget_curve_detects_diminishing_returns(stats):
    d = stats["diminishing_returns"]
    # leads per 1000: 20 at 500 ... 5 at 20000 -> clearly sub-proportional
    assert d["leads_per_1000_at_min_budget"] == 20.0
    assert d["leads_per_1000_at_max_budget"] == 5.0
    assert d["log_log_elasticity"] < 0.9
    assert d["verdict"] == "diminishing"
    assert [b["ad_budget"] for b in stats["budget_vs_leads"]] == [500, 1500, 2000, 5000, 6000, 20000]


def test_correlations_sorted_and_json_safe(stats):
    rs = [row["r"] for row in stats["correlations_with_profit"]]
    assert rs == sorted(rs, reverse=True)
    assert all(-1 <= r <= 1 for r in rs)  # constant columns are dropped, so no None
    cols = {row["column"] for row in stats["correlations_with_profit"]}
    assert "cumulative_profit" not in cols and "referred" in cols


def test_funnel_identities_hold_on_synthetic(stats):
    assert all(v == 1.0 for v in stats["funnel_consistency"].values())


def test_purchased_zero_profile(stats):
    pz = stats["purchased_zero_profile"]
    assert pz["n"] == 2 and pz["share_profit_positive"] == 0.0 and pz["upsell_positive"] == 0


def test_render_findings_contains_sections(stats):
    md = render_findings_md(stats)
    for heading in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5."):
        assert heading in md
    assert "D-M2-1" in md and "D-M2-2" in md


# --- real data: the numbers the gate and the report rely on ----------------------------


@pytest.fixture(scope="module")
def real_stats() -> dict:
    return overview_stats(clean(load_raw()))


def test_real_data_incomplete_rows_is_33(real_stats):
    assert real_stats["counts"]["incomplete_rows"] == 33
    assert real_stats["counts"]["missing_per_column"] == {"ltv_months": 4, "cumulative_profit": 29}


def test_real_data_has_three_tiers_and_consistent_funnel(real_stats):
    assert len(real_stats["conversion_by_tier"]) == 3
    assert all(v == 1.0 for v in real_stats["funnel_consistency"].values())
    assert real_stats["diminishing_returns"]["verdict"] == "diminishing"
