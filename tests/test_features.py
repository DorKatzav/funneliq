import pandas as pd
import pytest

from ml.data import clean, load_raw
from ml.features import (
    ALLOWED_OUTCOMES,
    ENGINEERED,
    FUNNEL_RAW,
    OUTCOMES,
    TASK_FEATURES,
    assert_no_leakage,
    build_features,
)


def _three_rows() -> pd.DataFrame:
    base = {c: [0, 0, 0] for c in FUNNEL_RAW}
    base.update(
        ad_budget=[500, 3000, 20000],
        num_leads=[10, 40, 0],  # third row: zero leads -> rates must be 0, not NaN
        leads_answered=[5, 30, 0],
        leads_not_answered=[5, 10, 0],
        closed=[1, 8, 0],
    )
    return pd.DataFrame(base)


def test_leakage_guard_rejects_outcomes():
    with pytest.raises(ValueError, match="leakage"):
        assert_no_leakage(["ad_budget", "cumulative_profit"], "ltv")
    with pytest.raises(ValueError, match="ltv_months"):
        assert_no_leakage(["ad_budget", "ltv_months"], "upsell_early")


def test_leakage_guard_allows_only_sanctioned_exceptions():
    assert_no_leakage(TASK_FEATURES["upsell_tenure"], "upsell_tenure")  # ltv_months allowed here
    with pytest.raises(ValueError):
        assert_no_leakage(["ad_budget", "referred"], "upsell_tenure")  # but not other outcomes


def test_every_task_feature_list_passes_its_own_guard():
    for task, names in TASK_FEATURES.items():
        assert_no_leakage(names, task)
        # and nothing outside the sanctioned list sneaks in
        assert not (set(names) & set(OUTCOMES)) - set(ALLOWED_OUTCOMES.get(task, []))


def test_build_features_returns_exact_columns_in_order():
    X = build_features(_three_rows(), "ltv")
    assert list(X.columns) == TASK_FEATURES["ltv"] == FUNNEL_RAW + ENGINEERED
    assert len(X) == 3


def test_engineered_values_and_zero_leads_safety():
    X = build_features(_three_rows(), "ltv")
    assert X.loc[0, "answer_rate"] == pytest.approx(0.5)
    assert X.loc[0, "conversion_rate"] == pytest.approx(0.1)
    assert X.loc[0, "cost_per_lead"] == pytest.approx(50.0)
    assert X.loc[1, "cost_per_lead"] == pytest.approx(75.0)
    assert (X.loc[2, ["answer_rate", "conversion_rate", "cost_per_lead"]] == 0).all()
    assert X["budget_tier"].tolist() == [0, 1, 2]  # Low, Mid, High codes


def test_categorical_tier_is_string_for_catboost():
    X = build_features(_three_rows(), "super", categorical=True)
    assert X["budget_tier"].tolist() == ["Low", "Mid", "High"]


def test_unknown_task_and_missing_columns_fail_loudly():
    with pytest.raises(KeyError):
        build_features(_three_rows(), "nope")
    with pytest.raises(ValueError, match="missing funnel columns"):
        build_features(_three_rows().drop(columns=["closed"]), "ltv")
    with pytest.raises(ValueError, match="ltv_months"):
        build_features(_three_rows(), "upsell_tenure")  # tenure variant needs ltv_months in the input


def test_real_data_builds_without_nans():
    df = clean(load_raw())
    X = build_features(df, "ltv")
    assert X.shape == (3500, len(TASK_FEATURES["ltv"]))
    assert not X.isna().any().any()
