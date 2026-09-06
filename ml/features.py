"""Feature policy — the single place that decides what a model is allowed to see.

Rule (D4, reinforced by the user on 2026-09-06): a feature is legitimate only if the
business holds it at prediction time. Everything that describes how the relationship
played out (lifetime, purchase, upsell, profit, referral) is an OUTCOME and can never
be a feature for another outcome, unless a task explicitly allows it with a written
justification in docs/REPORT.md.

`assert_no_leakage` is a test, not a comment: trainers call it, and tests/test_features.py
proves it raises.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data import TIERS, budget_tier

FUNNEL_RAW = [
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
]
ENGINEERED = ["answer_rate", "conversion_rate", "cost_per_lead", "budget_tier"]
OUTCOMES = ["ltv_months", "purchased", "upsell", "cumulative_profit", "referred"]

TASK_FEATURES: dict[str, list[str]] = {
    "ltv": FUNNEL_RAW + ENGINEERED,
    "upsell_early": FUNNEL_RAW + ENGINEERED,
    "upsell_tenure": FUNNEL_RAW + ENGINEERED + ["ltv_months"],
    "super": FUNNEL_RAW + ENGINEERED,
    "profit": FUNNEL_RAW + ENGINEERED,
}

# The only sanctioned exceptions; each needs a justification in docs/REPORT.md.
ALLOWED_OUTCOMES: dict[str, list[str]] = {
    "upsell_tenure": ["ltv_months"],  # upsell outreach targets existing customers whose tenure is known
}

TIER_CODES = {tier: i for i, tier in enumerate(TIERS)}  # Low=0, Mid=1, High=2


def assert_no_leakage(feature_names: list[str], task: str) -> None:
    """Raise ValueError if an outcome column is used as a feature without an explicit allowance."""
    allowed = set(ALLOWED_OUTCOMES.get(task, []))
    leaked = [f for f in feature_names if f in OUTCOMES and f not in allowed]
    if leaked:
        raise ValueError(f"leakage: task '{task}' must not use outcome columns as features: {leaked}")


def engineer(df: pd.DataFrame, categorical: bool = False) -> pd.DataFrame:
    """Add the ENGINEERED columns to a frame that has the FUNNEL_RAW columns."""
    out = df.copy()
    leads = out["num_leads"].astype(float)
    safe = leads.where(leads > 0, np.nan)
    out["answer_rate"] = (out["leads_answered"] / safe).fillna(0.0)
    out["conversion_rate"] = (out["closed"] / safe).fillna(0.0)
    out["cost_per_lead"] = (out["ad_budget"] / safe).fillna(0.0)
    tiers = budget_tier(out["ad_budget"])
    out["budget_tier"] = tiers.astype(str) if categorical else tiers.map(TIER_CODES).astype(int)
    return out


def build_features(df: pd.DataFrame, task: str, categorical: bool = False) -> pd.DataFrame:
    """Return exactly TASK_FEATURES[task], in order, with engineered columns computed.

    `categorical=True` keeps budget_tier as a string (for CatBoost's native handling);
    otherwise it is coded Low=0, Mid=1, High=2.
    """
    if task not in TASK_FEATURES:
        raise KeyError(f"unknown task '{task}'; known: {sorted(TASK_FEATURES)}")
    names = TASK_FEATURES[task]
    assert_no_leakage(names, task)
    missing = [c for c in FUNNEL_RAW if c not in df.columns]
    if missing:
        raise ValueError(f"input is missing funnel columns: {missing}")
    frame = engineer(df, categorical=categorical)
    extra = [c for c in names if c not in frame.columns]
    if extra:
        raise ValueError(f"input is missing columns required by task '{task}': {extra}")
    return frame[names].copy()
