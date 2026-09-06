import math

import pandas as pd
import pytest

from ml.data import (
    RAW_COLUMNS,
    budget_tier,
    clean,
    customers_only,
    incomplete_rows,
    load_raw,
    to_records,
)


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return load_raw()


@pytest.fixture(scope="module")
def cleaned(raw) -> pd.DataFrame:
    return clean(raw)


def test_raw_shape_and_columns(raw):
    assert raw.shape == (3500, 19)
    assert list(raw.columns) == RAW_COLUMNS


def test_incomplete_rows_count(raw):
    assert int(incomplete_rows(raw).sum()) == 33
    assert int(raw["ltv_months"].isna().sum()) == 4
    assert int(raw["cumulative_profit"].isna().sum()) == 29


def test_clean_adds_row_id_tier_and_bool_referred(cleaned, raw):
    assert cleaned.shape == (3500, 21)
    assert cleaned["row_id"].tolist() == list(range(3500))
    assert cleaned["referred"].dtype == bool
    assert int(cleaned["referred"].sum()) == int((raw["referred"] == "Yes").sum()) == 1354
    # cleaning never drops or fills anything
    assert int(incomplete_rows(cleaned).sum()) == 33


def test_budget_tier_boundaries_scalar():
    assert budget_tier(500) == "Low"
    assert budget_tier(1500) == "Low"
    assert budget_tier(2000) == "Mid"
    assert budget_tier(5000) == "Mid"
    assert budget_tier(6000) == "High"
    assert budget_tier(20000) == "High"


def test_budget_tier_series_matches_independent_computation(cleaned):
    expected = pd.cut(
        cleaned["ad_budget"], bins=[-1, 1500, 5000, 10**9], labels=["Low", "Mid", "High"]
    ).astype(str)
    assert (cleaned["budget_tier"] == expected).all()
    assert set(cleaned["budget_tier"].unique()) == {"Low", "Mid", "High"}


def test_clean_rejects_unknown_referred_value(raw):
    bad = raw.head(3).copy()
    bad.loc[0, "referred"] = "Maybe"
    with pytest.raises(ValueError, match="referred"):
        clean(bad)


def test_customers_only(cleaned):
    customers = customers_only(cleaned)
    assert len(customers) == 3163
    assert (customers["purchased"] == 1).all()


def test_to_records_is_json_safe(cleaned):
    records = to_records(cleaned.head(50))
    assert len(records) == 50
    assert records[0]["row_id"] == 0
    assert isinstance(records[0]["ad_budget"], int)
    assert isinstance(records[0]["referred"], bool)
    # the 2nd row of the CSV has a missing cumulative_profit? Not guaranteed — check globally instead.
    all_records = to_records(cleaned)
    missing_profit = [r for r in all_records if r["cumulative_profit"] is None]
    assert len(missing_profit) == 29
    assert not any(isinstance(v, float) and math.isnan(v) for r in all_records for v in r.values())
