"""Loading and cleaning the provided dataset — the single source of truth for cleaning rules.

Both training (ml/train_*.py) and serving (app/) go through these functions so a
model never sees an input shaped differently from what it was trained on.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "funnel_marketing_data.csv"

RAW_COLUMNS = [
    "ad_budget",
    "num_leads",
    "leads_answered",
    "leads_not_answered",
    "followup_1",
    "followup_2",
    "followup_3",
    "followup_4",
    "followup_5",
    "not_closed",
    "closed",
    "calls_to_closed",
    "calls_to_not_closed",
    "customer_acquisition_cost",
    "ltv_months",
    "purchased",
    "upsell",
    "cumulative_profit",
    "referred",
]

TIER_LOW_MAX = 1500  # Low  <= 1500
TIER_MID_MAX = 5000  # Mid  2000–5000 ; High > 5000
TIERS = ["Low", "Mid", "High"]


def load_raw(path: str | Path = DATA_PATH) -> pd.DataFrame:
    """Read the CSV exactly as provided; fail loudly if the columns are not what we expect."""
    df = pd.read_csv(path)
    if list(df.columns) != RAW_COLUMNS:
        raise ValueError(f"unexpected columns in {path}: {list(df.columns)}")
    return df


def budget_tier(ad_budget: pd.Series | float | int) -> pd.Series | str:
    """Low <= 1500, Mid 2000–5000, High > 5000. Works on a Series or a single number."""
    if isinstance(ad_budget, pd.Series):
        conditions = [ad_budget <= TIER_LOW_MAX, ad_budget <= TIER_MID_MAX]
        tiers = np.select(conditions, TIERS[:2], default=TIERS[2])
        return pd.Series(tiers, index=ad_budget.index, dtype="str")
    value = float(ad_budget)
    if value <= TIER_LOW_MAX:
        return "Low"
    if value <= TIER_MID_MAX:
        return "Mid"
    return "High"


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Type fixes and derived columns only. Nothing is dropped or imputed here.

    - `referred`: "Yes"/"No" -> bool
    - `budget_tier`: Low / Mid / High
    - `row_id`: the original CSV row index — the stable id shared with the database
    """
    out = df.copy()
    mapping = {"Yes": True, "No": False}
    unknown = set(out["referred"].dropna().unique()) - set(mapping)
    if unknown:
        raise ValueError(f"unexpected values in referred: {sorted(unknown)}")
    out["referred"] = out["referred"].map(mapping).astype(bool)
    out["budget_tier"] = budget_tier(out["ad_budget"])
    out.insert(0, "row_id", np.arange(len(out), dtype=int))
    return out


def customers_only(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that became customers (purchased == 1). Decision D-M2-1 records when this is applied."""
    return df[df["purchased"] == 1].copy()


def incomplete_rows(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows with at least one missing value."""
    return df.isna().any(axis=1)


def to_records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe rows for the database loader: NaN -> None, numpy scalars -> Python scalars."""
    frame = df.astype(object).where(df.notna(), None)
    records: list[dict] = []
    for row in frame.to_dict(orient="records"):
        records.append({k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()})
    return records
