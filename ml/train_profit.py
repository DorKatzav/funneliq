"""P6 — predict a campaign's cumulative profit from acquisition-time funnel data.

    python -m ml.train_profit

Data policy: every row with a recorded profit (non-purchasers keep their ₪0 — zero-profit campaigns
are real outcomes the simulator must see, D-M2-1); the 29 rows without a profit are dropped
(D-M2-2). Features: FUNNEL only. The best regressor by CV RMSE is served as models/profit.joblib;
the typical campaign per budget level is written to models/profiles.json for the simulator.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from ml.data import clean, load_raw
from ml.evaluate import cv_regression, importances
from ml.features import assert_no_leakage, build_features
from ml.registry import MODELS_DIR, save_metrics, utc_now
from ml.simulator import save_profiles, typical_profile
from ml.train_ltv import SEED, make_models


def training_frame() -> pd.DataFrame:
    df = clean(load_raw())
    return df[df["cumulative_profit"].notna()].reset_index(drop=True)


def profit_by_budget(df: pd.DataFrame) -> list[dict]:
    rows = []
    for budget, grp in df.groupby("ad_budget", sort=True):
        rows.append(
            {
                "ad_budget": int(budget),
                "n": int(len(grp)),
                "mean_profit": round(float(grp.cumulative_profit.mean()), 1),
                "median_profit": round(float(grp.cumulative_profit.median()), 1),
                "purchase_rate": round(float(grp.purchased.mean()), 4),
            }
        )
    return rows


def train(models_dir: Path = MODELS_DIR, n_splits: int = 5) -> dict:
    df = training_frame()
    X = build_features(df, "profit")
    y = df["cumulative_profit"].astype(float)
    assert_no_leakage(list(X.columns), "profit")

    cv: dict[str, dict] = {}
    imps: dict[str, dict] = {}
    fitted: dict[str, object] = {}
    for name, model in make_models().items():
        cv[name] = cv_regression(model, X, y, n_splits=n_splits, seed=SEED)
        model.fit(X, y)
        fitted[name] = model
        imps[name] = importances(model, list(X.columns))
        print(
            f"{name:9s} RMSE {cv[name]['rmse_mean']:,.0f} ± {cv[name]['rmse_std']:,.0f} | R² {cv[name]['r2_mean']:.3f}"
        )

    served = min(cv, key=lambda k: cv[k]["rmse_mean"])
    joblib.dump(fitted[served], models_dir / "profit.joblib")

    # Typical funnel per level from all 3,500 campaigns. The per-level expected profit the simulator uses is
    # the served model averaged over the REAL campaigns at that level (D-M7-1): predicting on the median profile
    # alone over-states skewed levels (e.g. ₪500) because the model is non-linear in the funnel counts.
    everything = clean(load_raw())
    profiles = typical_profile(everything)
    served_model = fitted[served]
    X_all = build_features(everything, "profit")
    preds = pd.Series(served_model.predict(X_all), index=everything.index).clip(lower=0.0)
    for level, prof in profiles["profiles"].items():
        mask = everything["ad_budget"] == int(level)
        prof["model_mean_profit"] = round(float(preds[mask].mean()), 1)
        typical = build_features(pd.DataFrame([prof["features"]]), "profit")
        prof["model_typical_profit"] = round(max(float(served_model.predict(typical)[0]), 0.0), 1)
    save_profiles(profiles, models_dir)

    payload = {
        "trained_at": utc_now(),
        "target": "cumulative_profit",
        "training_policy": "all rows with a recorded profit (non-purchasers at ₪0); 29 rows without profit dropped",
        "n_train": int(len(df)),
        "features": list(X.columns),
        "served": served,
        "cv": cv,
        "importances": imps,
        "profile_levels": profiles["levels"],
        "profit_by_budget": profit_by_budget(df),
        "target_stats": {
            "mean": round(float(y.mean()), 1),
            "std": round(float(y.std()), 1),
            "min": float(y.min()),
            "max": float(y.max()),
            "share_zero": round(float((y == 0).mean()), 4),
        },
    }
    save_metrics("profit", payload, models_dir)
    print(f"served: {served} | levels: {len(profiles['levels'])} | wrote {models_dir / 'metrics.json'}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    args.models_dir.mkdir(parents=True, exist_ok=True)
    result = train(args.models_dir)
    if args.json:
        print(json.dumps(result, indent=2))
