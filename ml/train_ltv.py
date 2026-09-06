"""P2 — predict customer lifetime (ltv_months) with three gradient-boosting regressors.

    python -m ml.train_ltv

Data policy (D-M2-1 / D-M2-2): customers only (purchased = 1), rows with a missing
target dropped. Features: FUNNEL only (see ml/features.py). An ablation re-runs the
best model WITH cumulative_profit to document how much a leaked outcome inflates R².
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from sklearn.ensemble import VotingRegressor
from xgboost import XGBRegressor

from ml.data import clean, customers_only, load_raw
from ml.evaluate import cv_regression, importances
from ml.features import FUNNEL_RAW, assert_no_leakage, build_features
from ml.registry import MODELS_DIR, save_metrics, utc_now

SEED = 42


def make_models(seed: int = SEED) -> dict[str, object]:
    return {
        "xgboost": XGBRegressor(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=seed,
            n_jobs=4,
        ),
        "lightgbm": LGBMRegressor(
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=15,
            subsample=0.9,
            subsample_freq=1,
            colsample_bytree=0.9,
            random_state=seed,
            verbose=-1,
            n_jobs=4,
            importance_type="gain",  # comparable with xgboost/catboost (split counts are not)
        ),
        "catboost": CatBoostRegressor(
            iterations=600, learning_rate=0.05, depth=4, random_seed=seed, verbose=0, thread_count=4
        ),
    }


def _report(name: str, m: dict) -> None:
    print(f"{name:9s} RMSE {m['rmse_mean']:.3f} ± {m['rmse_std']:.3f} | R² {m['r2_mean']:.3f}")


def representative_row(df: pd.DataFrame) -> dict[str, float]:
    """The actual customer closest (z-score distance) to the column medians — used as form defaults.

    Column-wise medians are NOT a valid funnel (answered + not answered may not equal leads),
    so we pick a real row instead.
    """
    cols = FUNNEL_RAW
    z = (df[cols] - df[cols].median()) / df[cols].std().replace(0, 1)
    idx = z.pow(2).sum(axis=1).idxmin()
    return {c: float(df.loc[idx, c]) for c in cols}


def training_frame() -> pd.DataFrame:
    df = customers_only(clean(load_raw()))
    return df[df["ltv_months"].notna()].reset_index(drop=True)


def train(models_dir: Path = MODELS_DIR, n_splits: int = 5) -> dict:
    df = training_frame()
    X = build_features(df, "ltv")
    y = df["ltv_months"].astype(float)
    assert_no_leakage(list(X.columns), "ltv")
    models = make_models()

    cv: dict[str, dict] = {}
    imps: dict[str, dict] = {}
    for name, model in models.items():
        cv[name] = cv_regression(model, X, y, n_splits=n_splits, seed=SEED)
        model.fit(X, y)
        joblib.dump(model, models_dir / f"ltv_{name}.joblib")
        imps[name] = importances(model, list(X.columns))
        _report(name, cv[name])

    ensemble = VotingRegressor([(n, m) for n, m in make_models().items()])
    cv["ensemble"] = cv_regression(ensemble, X, y, n_splits=n_splits, seed=SEED)
    _report("ensemble", cv["ensemble"])

    served = min(cv, key=lambda k: cv[k]["rmse_mean"])

    # --- ablation: what happens if the leaked outcome is allowed in? (never through TASK_FEATURES) ---
    abl_rows = df["cumulative_profit"].notna()
    X_abl = X[abl_rows].assign(cumulative_profit=df.loc[abl_rows, "cumulative_profit"].astype(float))
    y_abl = y[abl_rows]
    ablation = {
        "features": list(X_abl.columns),
        "n_rows": int(abl_rows.sum()),
        "catboost": cv_regression(make_models()["catboost"], X_abl, y_abl, n_splits=n_splits, seed=SEED),
        "catboost_funnel_only_same_rows": cv_regression(
            make_models()["catboost"], X[abl_rows], y_abl, n_splits=n_splits, seed=SEED
        ),
    }
    print(
        f"ablation  R² with profit {ablation['catboost']['r2_mean']:.3f} "
        f"vs funnel-only {ablation['catboost_funnel_only_same_rows']['r2_mean']:.3f}"
    )

    defaults = representative_row(df)  # a real customer nearest the medians: a valid funnel by construction
    payload = {
        "trained_at": utc_now(),
        "target": "ltv_months",
        "training_policy": (
            "customers only (purchased = 1); rows with missing ltv_months dropped (D-M2-1, D-M2-2)"
        ),
        "n_train": int(len(df)),
        "features": list(X.columns),
        "served": served,
        "cv": cv,
        "importances": imps,
        "ablation_with_profit": ablation,
        "input_defaults": defaults,
        "target_stats": {
            "mean": round(float(y.mean()), 2),
            "std": round(float(y.std()), 2),
            "min": float(y.min()),
            "max": float(y.max()),
        },
    }
    save_metrics("ltv", payload, models_dir)
    print(f"served: {served} | wrote {models_dir / 'metrics.json'}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--json", action="store_true", help="print the metrics payload")
    args = parser.parse_args()
    args.models_dir.mkdir(parents=True, exist_ok=True)
    result = train(args.models_dir)
    if args.json:
        print(json.dumps(result, indent=2))
